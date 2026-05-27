"""
Hybrid ranking engine — reranks top-200 candidates down to top-20.

THE FUNDAMENTAL PROBLEM THIS SOLVES:
──────────────────────────────────────
  Retrieval systems (BM25, dense embeddings) are optimized for RECALL.
  They find "everything that could possibly be relevant."
  They are NOT optimized for "what is MOST relevant."

  Think of it like a search party looking for a missing hiker:
  Retrieval = cast the widest net (200 candidates, don't miss the hiker)
  Ranking   = from those 200, figure out who is most likely the hiker

  A resume with skills=[Python, JS] applying to "Senior Python Backend Engineer
  with 5 years experience" should rank HIGHER than a resume with skills=[Python]
  but experience=["Python intern at startup, 3 months"].

  Embedding similarity alone cannot distinguish these well.
  We need STRUCTURED SIGNALS layered on top.

THE RANKING FORMULA:
──────────────────────
  final_score = (
      W_EMBED    * embedding_similarity_score  +   # semantic match (0-1)
      W_SKILLS   * skill_overlap_score         +   # keyword precision (0-1)
      W_EXP      * experience_score            +   # years of experience (0-1)
      W_QUALITY  * job_quality_score           +   # LLM quality signal (0-1)
      W_RECENCY  * recency_score               +   # how recent is the posting (0-1)
  )

  Each component is normalized to [0, 1] before weighting.
  Weights sum to 1.0.

WHY THESE SPECIFIC WEIGHTS:
────────────────────────────
  W_EMBED = 0.40 → Semantic similarity is still the primary signal.
    A job about "distributed systems" should match a candidate with
    "backend infrastructure" experience even without exact words.
    40% weight reflects this importance.

  W_SKILLS = 0.30 → Exact skill overlap is critical in tech hiring.
    A job requiring "React" where the candidate knows "Vue" is NOT a match
    even if they're both frontend frameworks (embedding would show similarity).
    30% weight penalizes exact skill mismatches.

  W_EXP = 0.15 → Experience matters but shouldn't dominate.
    A 3-year engineer can do a "senior" job if skills match.
    15% lets experience influence but not block good candidates.

  W_QUALITY = 0.10 → Job quality filtering.
    Prevents garbage jobs (missing descriptions, suspicious postings)
    from ranking high. 10% is enough to sort poor jobs to the bottom.

  W_RECENCY = 0.05 → Small recency boost.
    A 6-month-old job posting might be filled. Slight preference for new.
    5% — enough to break ties, not enough to bury older quality jobs.

  Total = 1.0

WHY NOT LEARN WEIGHTS (ML-based ranking):
───────────────────────────────────────────
  LambdaRank, LTR (Learning to Rank) would learn optimal weights from
  click data / application data. We don't have that yet.
  Handcrafted weights + evaluation (Day 33) gets us 80% of the value
  with 0% of the training data infrastructure.
  We can switch to LTR once we have enough behavioral signal (Day 35+).

RERANKING — WHY WE TAKE TOP 200 → TOP 20:
──────────────────────────────────────────
  "Retrieve many, rank few" is a classic two-stage IR architecture.
  Stage 1 (retrieval): maximize recall — get all possibly relevant results.
  Stage 2 (ranking): maximize precision — from candidates, pick the best.

  Why not retrieve 20 directly?
  Because retrieval is imprecise. If you only retrieve 20, you might miss
  the perfect candidate at position 21 who was just ranked slightly behind
  due to embedding noise.

  Why not rank 2000?
  Because ranking is expensive (it runs the full formula for each candidate).
  200 is the Goldilocks number: enough recall coverage, manageable rank cost.
  Amazon, Netflix, and Airbnb all use this two-stage approach.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Optional

from config import settings

logger = logging.getLogger(__name__)

# ── Ranking weights — must sum to 1.0 ────────────────────────────────────────
_W_EMBED   = 0.40
_W_SKILLS  = 0.30
_W_EXP     = 0.15
_W_QUALITY = 0.10
_W_RECENCY = 0.05

assert abs(_W_EMBED + _W_SKILLS + _W_EXP + _W_QUALITY + _W_RECENCY - 1.0) < 1e-9, \
    "Ranking weights must sum to 1.0"


# ── Experience scoring table ──────────────────────────────────────────────────
# Maps "years of experience required" → normalized score.
# WHY a lookup table instead of a formula:
#   Linear formula: 3 years req / 10 = 0.3, 5 years = 0.5.
#   But the job market is NOT linear. Going from 0→1 year is huge.
#   Going from 7→10 years barely matters. Log curve matches reality.
#   Table is explicit, debuggable, and easy to tune.
def _experience_score(candidate_years: float, required_years: float) -> float:
    """
    Score how well candidate experience matches job requirement.

    DECISION: we use a "more than required = full score" policy.
    A candidate with 8 years applying to a 3-year-req job gets 1.0.
    Under-experience is penalized progressively:
      50% below req  → 0.5 score
      at req         → 1.0 score
      above req      → 1.0 score (no penalty for being overqualified)

    WHY no overqualification penalty:
      That's a business rule for the HR team, not an algorithmic rule.
      The algorithm just ranks by fit — the human makes the overqualified call.
    """
    if required_years <= 0:
        return 1.0  # No experience requirement = full score

    if candidate_years >= required_years:
        return 1.0

    if candidate_years <= 0:
        return 0.1  # Zero experience gets a small floor (not zero — maybe a student)

    # Partial credit: how much of required experience does candidate have?
    ratio = candidate_years / required_years
    # Apply sqrt to make the curve less harsh for near-matches
    # candidate=3, required=5 → ratio=0.6 → sqrt(0.6)=0.775 (reasonable partial credit)
    return min(1.0, math.sqrt(ratio))


def _skill_overlap_score(candidate_skills: list[str], job_skills: list[str]) -> float:
    """
    Precision and recall of skill overlap.

    Uses F1 score — harmonic mean of precision and recall.

    WHY F1 instead of pure overlap:
      Pure overlap: if job needs 10 skills and candidate has 3/10, score=0.3
      But also: if candidate has 50 skills and matches 3, they might be a specialist
                in OTHER areas — precision (3/50 = 0.06) is low.
      F1 balances both: are you covering what the job needs AND is your skill
      set focused enough to be relevant?

      In practice: for tech roles, recall (covering job requirements) matters
      more than precision. A candidate with extra skills isn't penalized badly.
      F1 gives a balanced view without extreme punishment for either case.
    """
    if not job_skills:
        return 0.5  # No skill requirement data — neutral score

    if not candidate_skills:
        return 0.0

    candidate_set = {s.lower() for s in candidate_skills}
    job_set = {s.lower() for s in job_skills}

    # Normalize: check canonical forms match
    # (this is a simplified version — normalizer.py handles full canonicalization)
    intersection = candidate_set & job_set
    if not intersection:
        return 0.05  # Small floor — prevent zero for near misses

    precision = len(intersection) / len(candidate_set) if candidate_set else 0
    recall    = len(intersection) / len(job_set) if job_set else 0

    if precision + recall == 0:
        return 0.0

    f1 = 2 * precision * recall / (precision + recall)
    return round(f1, 4)


def _recency_score(posted_at_iso: str | None) -> float:
    """
    Score based on how recently the job was posted.

    Decay curve: exponential decay with 30-day half-life.
    Posted today → 1.0
    Posted 30 days ago → 0.5
    Posted 90 days ago → 0.125
    Posted 180 days ago → ~0.015

    WHY exponential decay (not linear):
      Linear: 30-day-old job = 0.9 score, 90-day = 0.7 score.
      But a 90-day-old job is much more likely to be filled than a 30-day-old one.
      Exponential decay models this reality better.

    WHY 30-day half-life:
      Most tech jobs fill within 30-60 days. After 90 days, most are stale.
      30-day half-life aggressively but not harshly discounts older postings.
    """
    if not posted_at_iso:
        return 0.5  # No date = neutral score

    try:
        posted_at = datetime.fromisoformat(posted_at_iso.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        days_old = (now - posted_at).days
        # Exponential decay: score = 0.5^(days/30)
        return round(math.pow(0.5, days_old / 30.0), 4)
    except (ValueError, TypeError):
        return 0.5


def rerank(
    candidates: list[dict],
    candidate_skills: list[str],
    candidate_experience_years: float = 0.0,
    top_n: int = 20,
) -> list[dict]:
    """
    Rerank a list of retrieved candidates using the full ranking formula.

    Args:
      candidates:                List from hybrid_retrieve() or retrieve_jobs()
                                 Each item: {job_id, score, metadata, ...}
      candidate_skills:          Normalized skill list from resume (canonical names)
      candidate_experience_years: Total years of experience estimated from resume
      top_n:                     Number of results to return after reranking

    Returns:
      Top N candidates with ranking_details added to each result.
      Sorted by final_score descending.

    WHY we accept candidate_skills + candidate_experience_years as args
    (instead of computing them inside):
      Single Responsibility. This function ranks — it doesn't parse resumes.
      The pipeline.py orchestrator computes these from the extraction result
      and passes them in. Easier to test: mock inputs, verify outputs.
    """
    if not candidates:
        return []

    ranked: list[dict] = []

    for candidate in candidates:
        metadata = candidate.get("metadata", {})

        # ── Component 1: Embedding similarity score ────────────────────────
        # The "score" from Pinecone is cosine similarity [0, 1].
        # From hybrid_retriever, "score" is already RRF-fused [0, ~0.03].
        # We normalize RRF scores to [0, 1] range for consistent weighting.
        raw_score = candidate.get("score", 0.0)
        # Normalize RRF score: typical max RRF = 1/61 ≈ 0.016 for rank 1 from one list.
        # With two lists contributing, max ≈ 0.033. We normalize to [0, 1] via /0.04.
        embed_score = min(1.0, raw_score / 0.04)

        # ── Component 2: Skill overlap ─────────────────────────────────────
        job_skills_raw = metadata.get("skills", [])
        skill_score = _skill_overlap_score(candidate_skills, job_skills_raw)

        # ── Component 3: Experience match ──────────────────────────────────
        required_years = float(metadata.get("min_experience", 0) or 0)
        exp_score = _experience_score(candidate_experience_years, required_years)

        # ── Component 4: Job quality score ────────────────────────────────
        # quality_score comes from the LLM quality scorer (Day 33).
        # Range: [0, 1]. Default 0.5 if not yet scored.
        quality_score = float(metadata.get("quality_score", 0.5) or 0.5)

        # ── Component 5: Recency ───────────────────────────────────────────
        recency_score = _recency_score(metadata.get("posted_at"))

        # ── Final weighted score ───────────────────────────────────────────
        final_score = (
            _W_EMBED   * embed_score   +
            _W_SKILLS  * skill_score   +
            _W_EXP     * exp_score     +
            _W_QUALITY * quality_score +
            _W_RECENCY * recency_score
        )

        # Attach ranking breakdown for explainability (Day 35)
        ranked.append({
            **candidate,
            "final_score": round(final_score, 6),
            "ranking_details": {
                "embed_score":   round(embed_score, 4),
                "skill_score":   round(skill_score, 4),
                "exp_score":     round(exp_score, 4),
                "quality_score": round(quality_score, 4),
                "recency_score": round(recency_score, 4),
                # Include weights for transparency
                "weights": {
                    "embed":   _W_EMBED,
                    "skills":  _W_SKILLS,
                    "exp":     _W_EXP,
                    "quality": _W_QUALITY,
                    "recency": _W_RECENCY,
                },
                # Skill overlap details for explanation
                "candidate_skills":      candidate_skills[:20],
                "job_skills":            job_skills_raw[:20],
                "matched_skills":        list(
                    {s.lower() for s in candidate_skills} &
                    {s.lower() for s in job_skills_raw}
                ),
                "missing_skills":        list(
                    {s.lower() for s in job_skills_raw} -
                    {s.lower() for s in candidate_skills}
                ),
            },
        })

    # Sort by final_score descending
    ranked.sort(key=lambda x: x["final_score"], reverse=True)

    logger.info(
        "Reranked %d candidates → top %d (score range: %.4f – %.4f)",
        len(candidates),
        min(top_n, len(ranked)),
        ranked[0]["final_score"] if ranked else 0,
        ranked[min(top_n, len(ranked)) - 1]["final_score"] if ranked else 0,
    )

    return ranked[:top_n]


def estimate_experience_years(experience: list[dict]) -> float:
    """
    Estimate total years of experience from structured experience list.

    WHY estimate (not exact):
      Duration strings in resumes are chaos:
        "Jan 2019 – Present", "2 years", "2019-2022", "3+ years"
      We parse what we can, fall back to 0 for unparseable entries.

    Strategy: sum months from each role, divide by 12.
    Handle overlapping roles (e.g., consulting + full-time simultaneously)
    by capping at 12 months per year (prevents double-counting).
    """
    import re
    from datetime import date

    total_months = 0

    for exp in experience:
        duration = str(exp.get("duration", ""))

        # Pattern: "2019 – 2022" or "2019-2021"
        year_range = re.search(r"(\d{4})\s*[-–—]\s*(\d{4}|present|current)", duration, re.IGNORECASE)
        if year_range:
            start_year = int(year_range.group(1))
            end_str = year_range.group(2).lower()
            end_year = date.today().year if end_str in ("present", "current") else int(end_str)
            months = max(0, (end_year - start_year) * 12)
            total_months += months
            continue

        # Pattern: "3 years" or "2.5 years" or "18 months"
        simple_years = re.search(r"(\d+(?:\.\d+)?)\s*(?:years?|yrs?)", duration, re.IGNORECASE)
        if simple_years:
            total_months += int(float(simple_years.group(1)) * 12)
            continue

        simple_months = re.search(r"(\d+)\s*months?", duration, re.IGNORECASE)
        if simple_months:
            total_months += int(simple_months.group(1))
            continue

        # If we can't parse duration, assume 12 months (1 year) as a conservative estimate
        if duration and len(duration) > 2:
            total_months += 12

    years = total_months / 12.0
    # Cap at 40 years — prevents wildly high values from parsing errors
    return round(min(40.0, years), 1)