"""
Vector retrieval via Pinecone — semantic job matching.

This module replaces the old keyword-matching retriever.py.

OLD retriever.py:
  query_terms = query.split()
  score = count of matching terms
  → pure keyword matching, no semantic understanding

NEW retriever.py:
  resume embedding → Pinecone ANN search → top-K semantically similar jobs
  → with metadata filters (location, experience, remote, salary)

WHY Pinecone (not Weaviate, Qdrant, Milvus):
  - Managed service: no vector DB infra to maintain
  - Metadata filtering built-in: filter during retrieval, not after
  - Simple Python SDK: upsert + query, nothing else needed
  - Scales without DevOps overhead

CRITICAL ARCHITECTURE PRINCIPLE:
  Pinecone = retrieval layer (NOT source of truth)
  Mongo = source of truth
  Redis = optimization layer

  If Pinecone loses data → re-embed from Mongo
  Pinecone stores vectors + metadata for retrieval only

WHY top 200 (not 20, not 2000):
  - "retrieve many, rank few" principle
  - 20 is too few: behavioral ranking needs candidates to reorder
  - 2000 is too many: ranking 2000 jobs is expensive
  - 200 is the sweet spot: enough diversity, manageable ranking cost

METADATA FILTERING:
  Happens DURING retrieval (inside Pinecone), not after.
  WHY:
    Filtering after retrieval wastes vector search budget.
    If you retrieve 200 then filter to 50, you paid for 200 but got 50.
    Filtering during retrieval means all 200 results pass the filters.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from pinecone import Pinecone

from config import settings
from embedder import generate_single_embedding

logger = logging.getLogger(__name__)

# Lazy-initialized Pinecone client (created on first use)
_pc: Optional[Pinecone] = None
_index = None


def _get_index():
    """
    Lazy init Pinecone client + index.

    WHY lazy:
      - Don't crash on import if Pinecone isn't configured
      - Tests can import this module without Pinecone running
      - Connection created once, reused for all requests
    """
    global _pc, _index
    if _index is None:
        if not settings.PINECONE_API_KEY:
            raise ValueError("PINECONE_API_KEY required for retrieval")
        _pc = Pinecone(api_key=settings.PINECONE_API_KEY)
        _index = _pc.Index(settings.PINECONE_INDEX_NAME)
        logger.info("Connected to Pinecone index: %s", settings.PINECONE_INDEX_NAME)
    return _index


# ─────────────────────────────────────────────────────────────────────────────
# Upsert (used by job ingestion pipeline)
# ─────────────────────────────────────────────────────────────────────────────
def upsert_job_embeddings(
    job_id: str,
    embeddings: list[list[float]],
    metadata: dict[str, Any],
) -> None:
    """
    Store job embeddings in Pinecone.

    Called during job ingestion (recruiter creates job → embed → store).
    NOT during feed requests.

    WHY metadata stored alongside vector:
      Pinecone can filter on metadata during ANN search.
      Storing location/experience/remote/salary here enables
      "semantic match + hard constraint" retrieval in one query.

    Vector ID format: job_{job_id}_{chunk_index}
      WHY include chunk_index: a job might have multiple chunks
      (title+skills chunk, description chunk). Each needs its own vector.
    """
    index = _get_index()

    vectors = []
    for i, embedding in enumerate(embeddings):
        vector_id = f"job_{job_id}_{i}"
        vectors.append({
            "id": vector_id,
            "values": embedding,
            "metadata": {
                "job_id": job_id,
                "chunk_index": i,
                **metadata,
            },
        })

    # Pinecone upsert supports batches up to 100
    batch_size = 100
    for batch_start in range(0, len(vectors), batch_size):
        batch = vectors[batch_start : batch_start + batch_size]
        index.upsert(vectors=batch)

    logger.info("Upserted %d vectors for job %s", len(vectors), job_id)


def upsert_resume_embeddings(
    user_id: str,
    embeddings: list[list[float]],
    chunk_types: list[str],
    metadata: dict[str, Any],
) -> None:
    """
    Store resume embeddings in Pinecone.

    Called during resume upload (candidate uploads resume → embed → store).
    These vectors are used for job-to-candidate matching (recruiter side).

    Vector ID format: resume_{user_id}_{chunk_index}
    """
    index = _get_index()

    vectors = []
    for i, embedding in enumerate(embeddings):
        vector_id = f"resume_{user_id}_{i}"
        vectors.append({
            "id": vector_id,
            "values": embedding,
            "metadata": {
                "user_id": user_id,
                "chunk_type": chunk_types[i] if i < len(chunk_types) else "unknown",
                **metadata,
            },
        })

    batch_size = 100
    for batch_start in range(0, len(vectors), batch_size):
        batch = vectors[batch_start : batch_start + batch_size]
        index.upsert(vectors=batch)

    logger.info("Upserted %d vectors for resume %s", len(vectors), user_id)


# ─────────────────────────────────────────────────────────────────────────────
# Retrieval (used by feed service)
# ─────────────────────────────────────────────────────────────────────────────
def retrieve_jobs(
    query_embedding: list[float],
    top_k: int | None = None,
    filters: dict[str, Any] | None = None,
) -> list[dict]:
    """
    Retrieve top-K semantically similar jobs from Pinecone.

    Args:
      query_embedding: resume chunk embedding (or composite embedding)
      top_k: number of results (default: settings.TOP_K_RETRIEVAL = 200)
      filters: metadata filters applied DURING retrieval
        Example: {"location": "Remote", "min_experience": {"$lte": 5}}

    Returns:
      List of {"job_id": str, "score": float, "metadata": dict}
      Sorted by semantic similarity (highest first).

    IMPORTANT:
      This returns job IDs + scores.
      Node backend fetches full job data from Mongo using these IDs.
      Pinecone does NOT store full job documents.
    """
    index = _get_index()
    k = top_k or settings.TOP_K_RETRIEVAL

    # Build Pinecone filter dict
    pinecone_filter = _build_filter(filters) if filters else None

    try:
        results = index.query(
            vector=query_embedding,
            top_k=k,
            include_metadata=True,
            filter=pinecone_filter,
        )
    except Exception as exc:
        logger.error("Pinecone retrieval failed: %s", exc)
        # Graceful degradation: return empty, don't crash the API
        return []

    matches = []
    seen_jobs = set()

    for match in results.get("matches", []):
        job_id = match["metadata"].get("job_id", "")
        # Deduplicate: a job with multiple chunk vectors
        # might appear multiple times. Keep highest score.
        if job_id and job_id not in seen_jobs:
            seen_jobs.add(job_id)
            matches.append({
                "job_id": job_id,
                "score": match["score"],
                "metadata": match["metadata"],
            })

    logger.info(
        "Retrieved %d unique jobs (top_k=%d, filters=%s)",
        len(matches),
        k,
        bool(filters),
    )
    return matches


def _build_filter(filters: dict[str, Any]) -> dict:
    """
    Convert simple filter dict to Pinecone filter format.

    Pinecone uses MongoDB-like filter syntax:
      {"field": {"$eq": value}}
      {"field": {"$in": [values]}}
      {"field": {"$gte": value}}

    We accept a simplified format and convert:
      {"location": "Remote"}         → {"location": {"$eq": "Remote"}}
      {"remote": True}               → {"remote": {"$eq": True}}
      {"min_experience": {"$lte": 5}} → passed through as-is
    """
    pinecone_filter = {}

    for key, value in filters.items():
        if isinstance(value, dict):
            # Already in operator format
            pinecone_filter[key] = value
        elif isinstance(value, list):
            pinecone_filter[key] = {"$in": value}
        else:
            pinecone_filter[key] = {"$eq": value}

    return pinecone_filter


# ─────────────────────────────────────────────────────────────────────────────
# Delete (cleanup)
# ─────────────────────────────────────────────────────────────────────────────
def delete_job_vectors(job_id: str) -> None:
    """Remove all vectors for a job (when job is deleted/deactivated)."""
    index = _get_index()
    # Delete by ID prefix — Pinecone supports this
    try:
        index.delete(filter={"job_id": {"$eq": job_id}})
        logger.info("Deleted vectors for job %s", job_id)
    except Exception as exc:
        logger.error("Failed to delete vectors for job %s: %s", job_id, exc)


def delete_resume_vectors(user_id: str) -> None:
    """Remove all vectors for a resume (when user re-uploads)."""
    index = _get_index()
    try:
        index.delete(filter={"user_id": {"$eq": user_id}})
        logger.info("Deleted vectors for resume %s", user_id)
    except Exception as exc:
        logger.error("Failed to delete vectors for resume %s: %s", user_id, exc)