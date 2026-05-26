"""
Resume processing pipeline — orchestrator module.

Pipeline flow:
  PDF upload
    ↓
  ingest.extract_text()          → raw text from PDF
    ↓
  extractor.extract_resume()     → structured fields (skills, experience, etc.)
    ↓
  normalizer.normalize_skills()  → canonical skill names + domain mapping
    ↓
  chunker.chunk_resume()         → embeddable text chunks with metadata
    ↓
  embedder.generate_embeddings() → vector embeddings   ← SKIPPED if no OpenAI key
    ↓
  retriever.upsert_*()           → store in Pinecone   ← SKIPPED if no Pinecone key
    ↓
  return structured result to Node backend

GRACEFUL DEGRADATION LADDER:
  No OpenAI key   → stages 1-4 complete, skip 5-6. Node gets full extraction.
  No Pinecone key → stages 1-5 complete, skip 6.   Node gets extraction + embeddings.
  OpenAI down     → stages 1-4 complete, retry 5 via BullMQ later.
  Pinecone down   → stages 1-5 complete, retry 6 via BullMQ later.

The response always includes an `embedding_skip_reason` field so Node backend
knows exactly WHY embeddings were skipped and whether to retry.
"""

from __future__ import annotations

import logging
from typing import Any

from ingest import extract_text
from extractor import extract_resume
from normalizer import normalize_skills, map_to_domains
from chunker import chunk_resume
from embedder import is_configured as openai_configured, generate_embeddings, generate_single_embedding
from config import settings

logger = logging.getLogger(__name__)

# Skip reasons — explicit enum-like strings so Node backend can switch on them
_SKIP_NO_KEY        = "openai_key_not_configured"
_SKIP_EMBED_FAILED  = "embedding_api_failed"
_SKIP_PINECONE_KEY  = "pinecone_key_not_configured"
_SKIP_PINECONE_DOWN = "pinecone_upsert_failed"
_SKIP_NO_USER       = "no_user_id_provided"


def run_pipeline(pdf_path: str, user_id: str | None = None) -> dict[str, Any]:
    """
    Full resume processing pipeline.

    Always returns extraction data (stages 1-4).
    Embedding + storage are best-effort — failures are logged
    and reported in the response, not raised as exceptions.

    Response shape:
    {
      "extraction":          {...},   # always present if resume parsed
      "normalized_skills":   [...],   # always present
      "domain_coverage":     {...},   # always present
      "chunks":              [...],   # always present if resume parsed
      "chunk_count":         int,
      "skill_count":         int,
      "embeddings_generated": bool,
      "vectors_stored":       bool,
      "embedding_skip_reason": str | None   # None = embeddings succeeded
    }
    """
    # ── Stage 1: PDF → raw text ──────────────────────────────────────────
    text = extract_text(pdf_path)
    if not text or len(text.strip()) < 50:
        return {
            "error": "Could not extract text from PDF — file may be scanned or empty"
        }

    logger.info("Stage 1 complete: %d chars extracted", len(text))

    # ── Stage 2: raw text → structured extraction ────────────────────────
    try:
        extraction = extract_resume(text)
    except Exception as exc:
        logger.exception("Extraction failed")
        return {"error": f"Resume extraction failed: {exc}"}

    skills     = extraction.get("skills", [])
    experience = extraction.get("experience", [])

    if not skills and not experience:
        return {"error": "No skills or experience found — check resume format"}

    logger.info(
        "Stage 2 complete: %d skills, %d experience entries",
        len(skills), len(experience),
    )

    # ── Stage 3: skill normalisation ─────────────────────────────────────
    normalized     = normalize_skills(skills)
    domain_coverage = map_to_domains(skills)

    # Extract canonical skills for ranking (Day 31)
    canonical_skills = [n["canonical"] for n in normalized if n["canonical"]]

    # Estimate total experience years for ranking (Day 31)
    from ranker import estimate_experience_years
    experience_years = estimate_experience_years(experience)

    logger.info(
        "Stage 3 complete: %d/%d skills recognized, %d domains, %.1f years exp",
        sum(1 for n in normalized if n["canonical"]),
        len(normalized),
        len(domain_coverage),
        experience_years,
    )

    # ── Stage 4: semantic chunking ───────────────────────────────────────
    chunks = chunk_resume(extraction)
    logger.info("Stage 4 complete: %d chunks", len(chunks))

    # Base result — always returned regardless of what happens in 5-6
    result: dict[str, Any] = {
        "extraction":          extraction,
        "normalized_skills":   normalized,
        "canonical_skills":    canonical_skills,          # Day 31: for ranking
        "experience_years":    experience_years,           # Day 31: for ranking
        "domain_coverage":     domain_coverage,
        "chunks":              [{"text": c["text"], "type": c["type"]} for c in chunks],
        "chunk_count":         len(chunks),
        "skill_count":         len(skills),
        "embeddings_generated": False,
        "vectors_stored":       False,
        "embedding_skip_reason": None,
    }

    if not chunks:
        result["embedding_skip_reason"] = "no_chunks_produced"
        return result

    # ── Stage 5: embedding generation ────────────────────────────────────
    # Check BEFORE calling — gives cleaner log message than catching ValueError
    if not openai_configured():
        logger.warning(
            "Stage 5 skipped — OPENAI_API_KEY not set. "
            "Add it to .env when ready. Extraction data is complete."
        )
        result["embedding_skip_reason"] = _SKIP_NO_KEY
        return result

    chunk_texts = [c["text"] for c in chunks]
    embeddings  = generate_embeddings(chunk_texts)  # returns [] on failure, never raises

    if not embeddings:
        logger.error("Stage 5 failed — embedding API returned empty")
        result["embedding_skip_reason"] = _SKIP_EMBED_FAILED
        return result

    result["embeddings_generated"] = True
    logger.info("Stage 5 complete: %d embeddings", len(embeddings))

    # ── Stage 6: Pinecone storage ─────────────────────────────────────────
    if not user_id:
        logger.info("Stage 6 skipped — no user_id provided (extraction-only mode)")
        result["embedding_skip_reason"] = _SKIP_NO_USER
        return result

    try:
        from retriever import upsert_resume_embeddings, _get_index

        # Quick check — will raise if PINECONE_API_KEY is missing
        _get_index()

        chunk_types = [c["type"] for c in chunks]
        metadata = {
            "skill_count":      len(skills),
            "experience_count": len(experience),
            "domain_count":     len(domain_coverage),
        }
        upsert_resume_embeddings(user_id, embeddings, chunk_types, metadata)
        result["vectors_stored"] = True
        result["embedding_skip_reason"] = None   # full success
        logger.info("Stage 6 complete: vectors stored in Pinecone")

    except ValueError as exc:
        # PINECONE_API_KEY missing
        logger.warning("Stage 6 skipped — Pinecone not configured: %s", exc)
        result["embedding_skip_reason"] = _SKIP_PINECONE_KEY

    except Exception as exc:
        # Pinecone reachable but failed (timeout, quota, etc.)
        logger.error("Stage 6 failed — Pinecone upsert error: %s", exc)
        result["embedding_skip_reason"] = _SKIP_PINECONE_DOWN

    return result


def run_retrieval(
    query_text: str,
    top_k:  int  | None = None,
    filters: dict | None = None,
    candidate_skills: list[str] | None = None,
    candidate_experience_years: float = 0.0,
    use_hybrid: bool = True,
) -> dict[str, Any]:
    """
    Retrieval pipeline: query text → embedding → hybrid search → rerank → top 20.

    ARCHITECTURE CHANGE (Day 30-31):
      OLD: query_text → dense embedding → Pinecone ANN → top 200
      NEW: query_text → dense embedding → BM25 + dense (hybrid/RRF) → top 200
                      → ranker (skill + exp + quality + recency) → top 20

    WHY two-stage (retrieve 200 → rank to 20):
      Stage 1 (retrieval): maximize RECALL — don't miss good candidates.
      Stage 2 (ranking): maximize PRECISION — surface the BEST candidates.
      This is how every production search system works (Google, Amazon, Netflix).

    Args:
      query_text:                  Resume text or user query for retrieval
      top_k:                       Number of retrieval candidates (default 200)
      filters:                     Pinecone metadata filters
      candidate_skills:            Canonical skills for ranking (from normalizer)
      candidate_experience_years:  Years of experience for ranking
      use_hybrid:                  If False, falls back to dense-only (for A/B testing)

    Returns {"matches": [...], "count": int} on success.
    Returns {"error": str, "matches": [], "skip_reason": str} on failure.
    Never raises.
    """
    if not openai_configured():
        logger.warning("Retrieval skipped — OPENAI_API_KEY not set")
        return {
            "error":       "OpenAI key not configured",
            "skip_reason": _SKIP_NO_KEY,
            "matches":     [],
            "count":       0,
        }

    query_embedding = generate_single_embedding(query_text)

    if not query_embedding:
        return {
            "error":   "Failed to generate query embedding",
            "matches": [],
            "count":   0,
        }

    try:
        # ── Stage 1: Hybrid or dense retrieval ────────────────────────────
        if use_hybrid:
            from hybrid_retriever import hybrid_retrieve
            raw_matches = hybrid_retrieve(
                query_text      = query_text,
                query_embedding = query_embedding,
                top_k           = top_k,
                filters         = filters,
            )
            retrieval_method = "hybrid"
        else:
            # Dense-only fallback (used for A/B testing comparison)
            from retriever import retrieve_jobs
            raw_matches = retrieve_jobs(query_embedding, top_k=top_k, filters=filters)
            retrieval_method = "dense"

        # ── Stage 2: Rerank top 200 → top 20 ──────────────────────────────
        if raw_matches and candidate_skills is not None:
            from ranker import rerank
            ranked_matches = rerank(
                candidates                = raw_matches,
                candidate_skills          = candidate_skills,
                candidate_experience_years = candidate_experience_years,
                top_n                     = settings.TOP_K_RERANK,
            )
            reranked = True
        else:
            # No candidate context for ranking — return retrieval results directly
            ranked_matches = raw_matches[:settings.TOP_K_RERANK]
            reranked = False

        return {
            "matches":          ranked_matches,
            "count":            len(ranked_matches),
            "retrieval_method": retrieval_method,
            "reranked":         reranked,
        }

    except ValueError as exc:
        return {
            "error":       str(exc),
            "skip_reason": _SKIP_PINECONE_KEY,
            "matches":     [],
            "count":       0,
        }
    except Exception as exc:
        logger.exception("Retrieval pipeline failed")
        return {"error": str(exc), "matches": [], "count": 0}