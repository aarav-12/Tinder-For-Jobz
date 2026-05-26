"""
LLM-based job quality scoring.

THE PROBLEM THIS SOLVES:
─────────────────────────
  Not all job postings are equal. Consider:

  Job A: "Software Engineer at Stripe. We're building the payments infrastructure
  of the internet. You'll work on distributed systems handling $1T+ in payments.
  Requirements: Python 3.10+, distributed systems, strong CS fundamentals."

  Job B: "SW eng needed. Good salary. React needed maybe. Apply ASAP."

  Without quality scoring, both jobs might rank equally in semantic retrieval
  because they're about "software engineering." That's wrong.

  Quality scoring DOES:
    - Penalize poorly written/incomplete job postings
    - Boost well-written, specific, detailed postings
    - Filter out spam/low-effort postings before they reach candidates
    - Improve overall feed quality without changing the retrieval logic

  This is the same principle as PageRank for web search:
  retrieval finds RELEVANT pages, quality scoring surfaces the GOOD relevant pages.

WHAT WE SCORE:
──────────────
  1. Completeness: Does the job have a title, description, skill requirements?
     A job missing its description is like a product listing without a photo.

  2. Specificity: "Good communication skills" = vague. "Experience with Kafka
     consumer groups and offset management" = specific. Specific = quality signal.

  3. Legitimacy: Real companies post jobs that sound like real companies.
     Red flags: "immediate hire," "no experience needed, earn $5000/week,"
     "must provide SSN before interview." We don't want these in the feed.

  4. Relevance density: Is the posting about the role (signal) or
     padded with company history/benefits boilerplate (noise)?

  All four scored 0-10 by LLM, averaged to final score normalized to [0, 1].

EVALUATION (Day 33 — precision@k):
────────────────────────────────────
  We generate quality scores offline for all jobs in the database.
  During evaluation: did high-quality jobs appear more in "successful" applies?
  Proxy metric before real data: do manually labeled "good" jobs score > 0.7?

CACHING STRATEGY:
──────────────────
  Quality score is computed ONCE per job (when job is created/updated).
  Stored in job metadata in Pinecone AND in MongoDB (source of truth).
  Not computed at query time — too slow (1-2s per job, can't do 200 jobs per query).
  This is the "precompute expensive signals, retrieve cheap signals" principle.
  Same as how Netflix computes recommendation models offline and serves cached results.

WHY LLM FOR QUALITY SCORING (not rules):
──────────────────────────────────────────
  Rules we could write: "description must be > 100 words."
  Problem: a 50-word, highly specific job description might be excellent.
           A 500-word generic job description might be garbage.
  LLMs can evaluate nuance that rules cannot.
  And since quality is computed once per job (not per query), latency is acceptable.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

_QUALITY_PROMPT = """Score this job posting on quality. Return ONLY valid JSON, no explanation.

JOB POSTING:
Title: {title}
Skills required: {skills}
Description: {description}

Score each dimension 0-10 where 10 = excellent:
- completeness: Are all key fields present? (title, skills, meaningful description)
- specificity: Are requirements concrete and detailed? (not just "good communication skills")
- legitimacy: Does this look like a real job from a real company? (not spam/scam)
- relevance_density: Is the content about the actual role? (not boilerplate padding)

Return exactly this JSON:
{{"completeness": X, "specificity": X, "legitimacy": X, "relevance_density": X, "overall_quality": X}}

Where overall_quality is your 0-10 holistic assessment.
Return only the JSON object. No markdown, no explanation."""


def _fallback_quality_score(title: str, skills: list[str], description: str) -> float:
    """
    Rule-based quality scoring when LLM is unavailable.

    This is the degraded-but-not-broken fallback.
    Simple heuristics that catch obvious quality issues.

    WHY have a fallback:
      LLM quality scoring happens offline (job creation time).
      If Ollama is down when a job is created, we use this fallback.
      The job is still indexed; it just gets a heuristic quality score.
      When Ollama comes back up, a background worker can re-score.
    """
    score = 0.5  # Neutral baseline

    # Presence of key fields
    if title and len(title) > 5:
        score += 0.1
    if skills and len(skills) >= 3:
        score += 0.1
    if description and len(description) > 100:
        score += 0.1

    # Specificity heuristic: specific technologies > generic phrases
    generic_phrases = {"communication", "teamwork", "fast learner", "self-starter", "passionate"}
    desc_lower = description.lower()
    generic_count = sum(1 for p in generic_phrases if p in desc_lower)
    if generic_count >= 3:
        score -= 0.1

    # Red flag detection
    red_flags = {"immediate hire", "earn $", "no experience needed", "unlimited earning"}
    if any(flag in desc_lower for flag in red_flags):
        score -= 0.3

    return round(min(1.0, max(0.0, score)), 2)


def score_job_quality(
    job_id: str,
    title: str,
    skills: list[str],
    description: str,
) -> dict:
    """
    Compute quality score for a job posting.

    Returns:
    {
      "job_id": str,
      "quality_score": float,   # normalized [0, 1]
      "dimensions": dict,       # individual dimension scores
      "method": "llm" | "heuristic",
      "error": str | None
    }

    NEVER raises. Uses heuristic fallback on any LLM failure.
    """
    desc_truncated = (description or "")[:800]  # Context budget: quality signal is in the first 800 chars

    prompt = _QUALITY_PROMPT.format(
        title       = title or "Not provided",
        skills      = ", ".join(skills[:15]) if skills else "Not provided",
        description = desc_truncated or "Not provided",
    )

    try:
        resp = httpx.post(
            f"{settings.OLLAMA_URL}/api/generate",
            json={
                "model":  settings.LLM_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.0,   # Deterministic scoring — same job = same score
                    "num_predict": 150,   # JSON response is short
                },
            },
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "")

        # Parse JSON from LLM response
        clean = re.sub(r"```(?:json)?|```", "", raw).strip()
        # Find the JSON object in case there's any preamble
        json_match = re.search(r"\{[^{}]+\}", clean, re.DOTALL)
        if not json_match:
            raise ValueError("No JSON object found in LLM response")

        parsed = json.loads(json_match.group())

        # Extract and validate scores
        dimensions = {
            "completeness":      max(0, min(10, int(parsed.get("completeness", 5)))),
            "specificity":       max(0, min(10, int(parsed.get("specificity", 5)))),
            "legitimacy":        max(0, min(10, int(parsed.get("legitimacy", 5)))),
            "relevance_density": max(0, min(10, int(parsed.get("relevance_density", 5)))),
        }
        overall_raw = max(0, min(10, int(parsed.get("overall_quality", 5))))

        # Blend LLM overall with dimension average for stability
        # WHY blend: LLM overall sometimes diverges from dimension scores.
        # Averaging anchors the overall to its components.
        dim_avg = sum(dimensions.values()) / len(dimensions)
        blended_raw = 0.6 * overall_raw + 0.4 * dim_avg

        # Normalize to [0, 1]
        quality_score = round(blended_raw / 10.0, 3)

        logger.info(
            "Quality scored job %s: %.2f (dims: completeness=%d, specificity=%d, "
            "legitimacy=%d, density=%d)",
            job_id, quality_score,
            dimensions["completeness"], dimensions["specificity"],
            dimensions["legitimacy"], dimensions["relevance_density"],
        )

        return {
            "job_id":        job_id,
            "quality_score": quality_score,
            "dimensions":    dimensions,
            "method":        "llm",
            "error":         None,
        }

    except httpx.ConnectError:
        logger.info("Ollama not available — using heuristic quality score for job %s", job_id)
    except Exception as exc:
        logger.error("Quality scoring failed for job %s: %s", job_id, exc)

    # Heuristic fallback
    heuristic_score = _fallback_quality_score(title, skills, description)
    return {
        "job_id":        job_id,
        "quality_score": heuristic_score,
        "dimensions":    {},
        "method":        "heuristic",
        "error":         "LLM unavailable — used heuristic fallback",
    }


def evaluate_retrieval_quality(
    retrieved_jobs: list[dict],
    relevant_job_ids: list[str],
    k_values: list[int] | None = None,
) -> dict:
    """
    Compute precision@k and recall@k for retrieval evaluation (Day 33).

    WHAT IS PRECISION@K:
      Of the top K retrieved results, how many are actually relevant?
      Retrieved top 10 = [job1, job3, job7, job2, ...job10]
      Relevant = [job1, job3, job5]
      precision@10 = 2/10 = 0.2 (2 relevant in top 10)

    WHAT IS RECALL@K:
      Of ALL relevant results, how many appear in top K?
      recall@10 = 2/3 = 0.67 (found 2 of 3 relevant jobs in top 10)

    WHY BOTH MATTER:
      High precision, low recall: you showed 2 good jobs but missed 5 others.
      High recall, low precision: you found all good jobs but flooded the user
                                  with 8 irrelevant ones.
      F1@K = harmonic mean of both — the balanced evaluation metric.

    PRACTICAL USE:
      We manually label "ground truth" relevance for a test set of resumes.
      Run our retrieval pipeline, compute precision@10, recall@10, F1@10.
      Compare before/after adding BM25 hybrid. If metrics improve → ship it.
      This is offline evaluation. Online eval = A/B test on real users (Day 35+).
    """
    if not k_values:
        k_values = [5, 10, 20]

    relevant_set = set(relevant_job_ids)
    retrieved_ids = [r.get("job_id", "") for r in retrieved_jobs]

    metrics = {}
    for k in k_values:
        top_k = retrieved_ids[:k]
        hits = sum(1 for job_id in top_k if job_id in relevant_set)

        precision = hits / k if k > 0 else 0.0
        recall    = hits / len(relevant_set) if relevant_set else 0.0
        f1        = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

        metrics[f"precision@{k}"] = round(precision, 4)
        metrics[f"recall@{k}"]    = round(recall, 4)
        metrics[f"f1@{k}"]        = round(f1, 4)

    logger.info("Retrieval evaluation: %s", metrics)
    return metrics