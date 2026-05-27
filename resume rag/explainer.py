"""
RAG-based job explanation — "Why this job matches you."

WHY THIS IS RETRIEVAL-FIRST, NOT CHATBOT-FIRST:
─────────────────────────────────────────────────
  Most AI job products build a chatbot that "searches" for jobs.
  The problem: chatbots are optimized for conversation, not retrieval.
  They hallucinate job details, make up requirements, and can't
  guarantee that explanations are grounded in actual job data.

  Our system is RETRIEVAL-FIRST:
    1. Retrieve real jobs via BM25 + dense embeddings (verified data)
    2. Rank them via our formula (structured logic)
    3. THEN use AI only for explanation (grounded in real retrieved data)

  AI explains what the retrieval system already found.
  AI does NOT decide what to retrieve.
  This is why hallucination is nearly impossible in our explanations:
  the AI only sees the job we retrieved + the candidate's actual data.

RAG (Retrieval Augmented Generation) PATTERN:
──────────────────────────────────────────────
  Traditional LLM: "Why does this job match?" → LLM makes up reasons.
  RAG: Give LLM the actual job + candidate data → LLM explains based on facts.

  Context window = the "retrieved" documents given to the LLM.
  The LLM's job is GENERATION (writing explanation), not RETRIEVAL (finding facts).
  This is the grounding principle: generation is constrained by retrieved context.

  In our case:
    Retrieved context = {job posting data + candidate resume data + ranking breakdown}
    Generation = "explain why this specific candidate matches this specific job"

  The explanation is grounded in REAL numbers from our ranker:
  skill_score, exp_score, matched_skills, missing_skills.
  The LLM formats these into human-readable prose. That's all it does.

WHY OLLAMA (local LLM) NOT OPENAI FOR EXPLANATIONS:
──────────────────────────────────────────────────────
  OpenAI is used for embeddings (paid, high-quality, consistent vectors).
  Ollama is used for text generation (free, local, good enough for explanation).
  This is the cost architecture:
    - High-value ML operation (embedding): paid OpenAI
    - Text generation (explanation): free local Ollama
  At scale: 10k explanations/day via OpenAI = $50/day.
                                 via Ollama = $0/day (just compute).

  IF OLLAMA IS NOT RUNNING: explainer returns a template-based explanation.
  Graceful degradation: never fail because the explanation service is down.
  The job match is real regardless of whether we can explain it prettily.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from config import settings

logger = logging.getLogger(__name__)

_EXPLAIN_PROMPT = """You are a helpful career coach explaining job matches to candidates.

CANDIDATE PROFILE:
- Skills: {candidate_skills}
- Experience: {experience_years} years
- Domain coverage: {domains}

JOB POSTING:
- Title: {job_title}
- Required skills: {job_skills}
- Description: {job_description}

MATCH ANALYSIS (from our ranking system):
- Overall match score: {final_score:.0%}
- Skill match: {skill_score:.0%} ({matched_skills} skills matched, missing: {missing_skills})
- Experience match: {exp_score:.0%}
- Job freshness: {recency_score:.0%}

Write a 3-4 sentence explanation of why this job is a good match for this candidate.
Be specific. Reference actual skills and experience. Be honest about gaps.
Do NOT make up skills the candidate doesn't have.
Do NOT make up job requirements that aren't listed.
Keep it encouraging but realistic.
Output ONLY the explanation. No headers, no lists, no markdown."""


def _template_explanation(
    job_title: str,
    matched_skills: list[str],
    missing_skills: list[str],
    final_score: float,
    exp_score: float,
) -> str:
    """
    Fallback template-based explanation when Ollama is unavailable.

    WHY a template fallback:
      Explanation is a UX feature, not a correctness feature.
      The match is already computed. If the LLM is down, we still show
      the job with a basic explanation. Never block user experience
      on optional enhancement features.
    """
    skill_clause = ""
    if matched_skills:
        skill_clause = f"Your skills in {', '.join(matched_skills[:3])} directly match what they're looking for."

    gap_clause = ""
    if missing_skills:
        gap_clause = f" You may want to brush up on {', '.join(missing_skills[:2])} before applying."

    score_phrase = "strong" if final_score > 0.7 else "solid" if final_score > 0.5 else "partial"

    return (
        f"This {job_title} role shows a {score_phrase} match with your profile. "
        f"{skill_clause}"
        f" Your experience level aligns {'well' if exp_score > 0.7 else 'reasonably'} with their requirements."
        f"{gap_clause}"
    )


def explain_match(
    job_data: dict[str, Any],
    candidate_data: dict[str, Any],
    ranking_details: dict[str, Any],
) -> str:
    """
    Generate a human-readable explanation of why a job matches a candidate.

    Args:
      job_data:        Job metadata (title, skills, description)
      candidate_data:  Candidate info (skills, experience_years, domains)
      ranking_details: Output from ranker.rerank() ranking_details field

    Returns:
      A 3-4 sentence explanation string.
      Falls back to template if LLM unavailable.
      NEVER raises.

    GROUNDING PRINCIPLE:
      Every claim in the explanation is backed by data in the inputs.
      The LLM is instructed to ONLY use provided data.
      We pass matched_skills and missing_skills explicitly so the LLM
      doesn't have to "figure out" the overlap — we computed it already.
    """
    job_title    = job_data.get("title", "this role")
    job_skills   = job_data.get("skills", [])
    job_desc     = (job_data.get("description", "") or "")[:400]  # context budget

    matched_skills = ranking_details.get("matched_skills", [])
    missing_skills = ranking_details.get("missing_skills", [])
    final_score    = ranking_details.get("final_score", 0.5)
    skill_score    = ranking_details.get("skill_score", 0.5)
    exp_score      = ranking_details.get("exp_score", 0.5)
    recency_score  = ranking_details.get("recency_score", 0.5)

    candidate_skills = candidate_data.get("skills", [])
    experience_years = candidate_data.get("experience_years", 0)
    domains          = list(candidate_data.get("domain_coverage", {}).keys())

    prompt = _EXPLAIN_PROMPT.format(
        candidate_skills  = ", ".join(candidate_skills[:15]) or "not specified",
        experience_years  = experience_years,
        domains           = ", ".join(domains) or "general",
        job_title         = job_title,
        job_skills        = ", ".join(job_skills[:10]) or "not specified",
        job_description   = job_desc or "not provided",
        final_score       = final_score,
        skill_score       = skill_score,
        exp_score         = exp_score,
        recency_score     = recency_score,
        matched_skills    = ", ".join(matched_skills[:5]) or "none",
        missing_skills    = ", ".join(missing_skills[:3]) or "none",
    )

    try:
        resp = httpx.post(
            f"{settings.OLLAMA_URL}/api/generate",
            json={
                "model":  settings.LLM_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.3,   # Slightly creative (not 0) — explanations benefit from natural language variation
                    "num_predict": 200,   # 3-4 sentences = ~150 tokens, 200 gives buffer
                },
            },
            timeout=30,
        )
        resp.raise_for_status()
        explanation = resp.json().get("response", "").strip()

        if explanation and len(explanation) > 20:
            logger.info("LLM explanation generated (%d chars)", len(explanation))
            return explanation

        logger.warning("LLM returned empty/short explanation — using template")

    except httpx.ConnectError:
        logger.info("Ollama not running — using template explanation (expected in prod)")
    except Exception as exc:
        logger.error("Explanation LLM failed: %s", exc)

    # Fallback to template
    return _template_explanation(
        job_title      = job_title,
        matched_skills = matched_skills,
        missing_skills = missing_skills,
        final_score    = final_score,
        exp_score      = exp_score,
    )


def batch_explain(
    matches: list[dict],
    candidate_data: dict[str, Any],
    max_explanations: int = 5,
) -> list[dict]:
    """
    Generate explanations for the top N matches.

    WHY only top N (not all 20):
      LLM calls are slow (1-3s each). Explaining all 20 results = 20-60s.
      Users only read the top 5 before deciding to apply.
      Generate explanations for top 5 — lazy-load rest if needed.

    Returns each match with an added "explanation" field.
    """
    results = []
    for i, match in enumerate(matches):
        ranking_details = match.get("ranking_details", {})
        # Pass final_score into ranking_details for the LLM prompt
        ranking_details_with_score = {
            **ranking_details,
            "final_score": match.get("final_score", ranking_details.get("embed_score", 0.5)),
        }

        if i < max_explanations:
            job_data = {
                "title":       match.get("metadata", {}).get("title", ""),
                "skills":      match.get("metadata", {}).get("skills", []),
                "description": match.get("metadata", {}).get("description", ""),
            }
            explanation = explain_match(job_data, candidate_data, ranking_details_with_score)
        else:
            explanation = None  # Not generated yet — client can request on demand

        results.append({**match, "explanation": explanation})

    return results