"""
Hybrid retrieval — combines BM25 (sparse) + embeddings (dense) via RRF.

THE CORE INSIGHT (why hybrid > either alone):
─────────────────────────────────────────────
  Imagine two job retrieval systems competing:

  System A (dense only):
    Query: "Python backend engineer with Kubernetes experience"
    Returns: jobs that are semantically about "backend infrastructure"
    Problem: misses a job that says "Python, k8s, microservices" because
             the embedding of "k8s" sits slightly far from "Kubernetes" in
             vector space (different tokenization by the embedding model).

  System B (BM25 only):
    Same query.
    Returns: jobs with exact words "Python", "Kubernetes", "backend", "engineer"
    Problem: misses jobs that say "Python developer managing container orchestration"
             which is PERFECT for the candidate but doesn't say "Kubernetes" literally.

  System C (hybrid = A + B):
    Takes BOTH result lists.
    Uses RRF to combine: a job appearing in BOTH lists gets boosted.
    A job only in dense: still included (may have semantic match).
    A job only in BM25: still included (exact keyword match).
    A job in BOTH: ranked highest (double signal of quality).

  This is exactly how Google, Elastic, and Pinecone's own hybrid search work.

RECIPROCAL RANK FUSION (RRF) — the fusion algorithm:
──────────────────────────────────────────────────────
  PROBLEM: BM25 scores are in range [0, ~15]. Dense scores are in [0, 1].
  You can't just add them — they're different scales.

  NAIVE APPROACH (wrong): normalize both to [0,1] then add.
  PROBLEM: if BM25 has 5 docs and dense has 200, the normalization
  makes BM25 doc #5 score 0.0 and dense doc #200 also scores 0.0.
  They look equivalent but they're not.

  RRF APPROACH (correct):
    For each doc in each list, score = 1 / (rank + k)
    where k=60 is a smoothing constant (prevents rank 1 from dominating).

    Dense rank 1 → 1/61 = 0.0164
    Dense rank 10 → 1/70 = 0.0143
    Dense rank 100 → 1/160 = 0.00625

    A doc at rank 1 in BOTH lists:
      RRF score = 1/61 + 1/61 = 0.0328

    A doc at rank 1 in dense, rank 200 in BM25:
      RRF score = 1/61 + 1/260 = 0.0164 + 0.0038 = 0.0202

    A doc at rank 1 in BM25 only (not in dense):
      RRF score = 1/61 = 0.0164

  Result: docs appearing in BOTH lists consistently outscore single-list docs.
  This is rank-based, not score-based — immune to scale differences.

  WHY k=60 specifically:
    Originally chosen in the 2009 RRF paper (Cormack, Clarke, Buettcher).
    It limits the advantage of being at rank 1 vs rank 2.
    k=60 means rank 1 scores 1/61 and rank 2 scores 1/62 — small difference.
    k=1 would make rank 1 score 1.0 and rank 2 score 0.5 — too extreme.

ALPHA PARAMETER — weighting dense vs sparse:
────────────────────────────────────────────
  config.HYBRID_ALPHA controls how much we trust dense vs BM25.
  alpha=1.0 → pure dense (embedding only)
  alpha=0.0 → pure BM25 (keyword only)
  alpha=0.7 → 70% dense + 30% BM25 (our default)

  WHY 0.7 for alpha:
    For resume-to-job matching, semantic meaning matters more than exact keywords.
    A developer who knows "React" should match jobs saying "frontend development"
    even without the word "React". Dense retrieval captures this.
    But keyword matching catches edge cases (exact technology names, acronyms).
    70/30 is the standard starting point — tune based on offline eval (Day 33).

  HOW alpha interacts with RRF:
    We compute RRF scores independently for each list.
    Then: final_score = alpha * dense_rrf + (1 - alpha) * bm25_rrf
    This lets alpha control contribution without destroying RRF's rank-based math.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from config import settings
from bm25_retriever import search_jobs_bm25

logger = logging.getLogger(__name__)

# RRF smoothing constant — do NOT change without re-evaluating rankings.
# 60 is the standard from the original RRF paper.
_RRF_K = 60


def _rrf_score(rank: int) -> float:
    """Convert a rank to an RRF score. Rank is 1-indexed."""
    return 1.0 / (_RRF_K + rank)


def _ranks_to_rrf(items: list[tuple[str, float]]) -> dict[str, float]:
    """
    Convert a list of (doc_id, score) sorted by score descending
    into a dict of {doc_id: rrf_score}.

    Input is already sorted (highest score = rank 1).
    """
    return {doc_id: _rrf_score(rank + 1) for rank, (doc_id, _) in enumerate(items)}


def hybrid_retrieve(
    query_text: str,
    query_embedding: list[float],
    top_k: int | None = None,
    filters: dict[str, Any] | None = None,
    alpha: float | None = None,
) -> list[dict]:
    """
    Hybrid retrieval: BM25 + dense embeddings fused via RRF.

    Args:
      query_text:      Raw text query (used for BM25)
      query_embedding: Pre-computed dense embedding vector (used for Pinecone)
      top_k:           Number of final results to return
      filters:         Pinecone metadata filters (applied to dense only —
                       BM25 doesn't support structured filters natively)
      alpha:           Dense weight. None = use config.HYBRID_ALPHA

    Returns:
      List of {"job_id", "score", "dense_score", "bm25_score",
               "dense_rank", "bm25_rank", "metadata"}
      Sorted by hybrid RRF score descending.

    NEVER raises. On any failure returns whatever partial results we have.

    DESIGN DECISION — why filters only on dense, not BM25:
      BM25 is an in-memory index without metadata structure.
      Adding filter support to BM25 would require storing metadata per doc
      and post-filtering, which defeats the purpose of metadata filtering
      (you want to filter DURING retrieval to get k results that all pass filters).
      Solution: dense retrieval does the metadata filtering; BM25 adds keyword signal
      on top. The fusion step naturally weights down BM25-only results that
      wouldn't pass filters anyway (they'll score lower overall).
      For stricter filter enforcement: apply filters as post-filter step after fusion.
    """
    k = top_k or settings.TOP_K_RETRIEVAL
    _alpha = alpha if alpha is not None else settings.HYBRID_ALPHA

    # ── Dense retrieval (Pinecone ANN) ─────────────────────────────────────
    dense_results: list[dict] = []
    try:
        from retriever import retrieve_jobs
        dense_results = retrieve_jobs(query_embedding, top_k=k, filters=filters)
    except Exception as exc:
        logger.error("Dense retrieval failed in hybrid: %s", exc)
        # Continue with BM25 only — graceful degradation

    # ── Sparse retrieval (BM25) ────────────────────────────────────────────
    bm25_scores = search_jobs_bm25(query_text, top_k=k)

    # ── Early exit if both failed ──────────────────────────────────────────
    if not dense_results and not bm25_scores:
        logger.warning("Both dense and BM25 retrieval returned empty")
        return []

    # ── Convert to (job_id, score) sorted lists for RRF ───────────────────
    dense_sorted = [(r["job_id"], r["score"]) for r in dense_results]
    bm25_sorted  = sorted(bm25_scores.items(), key=lambda x: x[1], reverse=True)

    # ── Compute RRF scores ─────────────────────────────────────────────────
    dense_rrf = _ranks_to_rrf(dense_sorted)
    bm25_rrf  = _ranks_to_rrf(bm25_sorted)

    # ── Merge: union of all job IDs from both lists ────────────────────────
    all_job_ids = set(dense_rrf.keys()) | set(bm25_rrf.keys())

    # ── Build rank lookup for explainability ──────────────────────────────
    # WHY store ranks: Day 35 needs to explain WHY a job ranked highly.
    # "Appeared at rank 3 in keyword search AND rank 7 in semantic search" is
    # a meaningful explanation. Raw scores are not human-readable.
    dense_rank_map = {job_id: rank + 1 for rank, (job_id, _) in enumerate(dense_sorted)}
    bm25_rank_map  = {job_id: rank + 1 for rank, (job_id, _) in enumerate(bm25_sorted)}

    # ── Build metadata lookup from dense results ───────────────────────────
    metadata_map: dict[str, dict] = {
        r["job_id"]: r.get("metadata", {}) for r in dense_results
    }

    # ── Compute hybrid score for each job ─────────────────────────────────
    fused: list[dict] = []
    for job_id in all_job_ids:
        d_rrf = dense_rrf.get(job_id, 0.0)
        b_rrf = bm25_rrf.get(job_id, 0.0)

        # Weighted fusion: alpha controls dense vs BM25 contribution
        hybrid_score = _alpha * d_rrf + (1 - _alpha) * b_rrf

        fused.append({
            "job_id":     job_id,
            "score":      round(hybrid_score, 6),
            # Component scores for explainability (Day 35)
            "dense_rrf":  round(d_rrf, 6),
            "bm25_rrf":   round(b_rrf, 6),
            # Ranks for explainability
            "dense_rank": dense_rank_map.get(job_id),  # None if not in dense list
            "bm25_rank":  bm25_rank_map.get(job_id),   # None if not in BM25 list
            # Signal type — useful for debugging and explanation
            "retrieval_signals": _signal_type(job_id, dense_rrf, bm25_rrf),
            "metadata": metadata_map.get(job_id, {}),
        })

    # Sort by hybrid score descending, return top_k
    fused.sort(key=lambda x: x["score"], reverse=True)
    results = fused[:k]

    logger.info(
        "Hybrid retrieval: dense=%d, bm25=%d, union=%d, returned=%d (alpha=%.2f)",
        len(dense_results),
        len(bm25_scores),
        len(all_job_ids),
        len(results),
        _alpha,
    )
    return results


def _signal_type(
    job_id: str,
    dense_rrf: dict[str, float],
    bm25_rrf: dict[str, float],
) -> str:
    """
    Classify which retrieval system(s) found this job.

    Used in explainability layer (Day 35).
    "both"    → strong signal: appeared in semantic AND keyword search
    "dense"   → only semantically similar (no keyword overlap)
    "bm25"    → only keyword match (no semantic similarity)
    """
    in_dense = job_id in dense_rrf and dense_rrf[job_id] > 0
    in_bm25  = job_id in bm25_rrf and bm25_rrf[job_id] > 0

    if in_dense and in_bm25:
        return "both"
    elif in_dense:
        return "dense"
    else:
        return "bm25"