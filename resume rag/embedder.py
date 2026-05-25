"""
Embedding generator — converts text chunks into vectors.

WHY OpenAI embeddings (not Ollama, not Sentence-Transformers):
  - Production quality: text-embedding-3-small is battle-tested
  - Consistent dimensionality (1536) across all inputs
  - Simplest integration: one HTTP call, no model loading
  - Focus on architecture, not model fine-tuning

WHY batching:
  - OpenAI charges per token, not per request
  - Batching reduces HTTP overhead (1 call for 20 chunks vs 20 calls)
  - API rate limits hit slower with fewer requests

WHY retries with exponential backoff:
  - Embedding APIs fail (429 rate limits, 5xx server errors)
  - Transient failures should NOT kill the pipeline
  - Exponential backoff prevents thundering herd on recovery
  - Same principle as BullMQ retry classification:
    transient = retry, deterministic = fail fast

CRITICAL DESIGN DECISION:
  Embeddings are generated at INGEST TIME, not request time.
  - Resume upload → generate embeddings → store in Pinecone
  - Feed request → retrieve from Pinecone (already embedded)
  This is the "precompute vs request-time" principle from the architecture doc.

KEY BEHAVIOUR — NO API KEY:
  generate_embeddings() returns [] (empty list), NOT a crash.
  generate_single_embedding() returns None, NOT a crash.
  The caller (pipeline.py) sees an empty result and sets
  embeddings_generated=False + embedding_skip_reason="no_api_key".
  Extraction still completes and Node backend still gets parsed data.
  This is the same graceful degradation principle as Redis failures.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

# ── Retry configuration ──────────────────────────────────────────────────────
_MAX_RETRIES = 3
_BASE_DELAY = 1.0  # seconds
_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}  # transient errors only


def _should_retry(status_code: int, attempt: int) -> bool:
    """
    Retry classification:
      429 (rate limit)   → transient → retry with backoff
      5xx (server error) → transient → retry with backoff
      4xx (bad request)  → deterministic → fail immediately
    """
    if attempt >= _MAX_RETRIES:
        return False
    return status_code in _RETRY_STATUS_CODES


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff: 1s → 2s → 4s."""
    return _BASE_DELAY * (2 ** attempt)


def is_configured() -> bool:
    """
    Returns True if OpenAI key is present.
    Used by pipeline to decide whether to attempt embedding
    without having to catch exceptions.
    """
    return bool(settings.OPENAI_API_KEY and settings.OPENAI_API_KEY.strip())


def generate_embeddings(texts: list[str]) -> list[list[float]]:
    """
    Generate embeddings for a list of texts using OpenAI API.

    Returns [] (empty list) if:
      - texts is empty
      - OPENAI_API_KEY is not configured
      - all retries exhausted

    NEVER raises. Caller checks len(result) == 0 to detect failure.
    This design means embedding failure can NEVER crash the pipeline.

    Returns: list of embedding vectors in same order as input texts.
    """
    if not texts:
        return []

    if not is_configured():
        logger.warning(
            "OPENAI_API_KEY not set — skipping embedding generation. "
            "Extraction will still complete."
        )
        return []

    all_embeddings: list[list[float]] = []
    batch_size = settings.BATCH_SIZE

    for batch_start in range(0, len(texts), batch_size):
        batch = texts[batch_start : batch_start + batch_size]
        batch_embeddings = _embed_batch(batch)

        if not batch_embeddings:
            # One batch failed after all retries — stop here,
            # return what we have so far rather than partial corrupt data
            logger.error(
                "Batch %d/%d failed — returning empty to signal full failure",
                batch_start // batch_size + 1,
                (len(texts) + batch_size - 1) // batch_size,
            )
            return []

        all_embeddings.extend(batch_embeddings)

        # Small pause between batches — avoids rate limit bursts
        if batch_start + batch_size < len(texts):
            time.sleep(0.1)

    logger.info(
        "Generated %d embeddings (model=%s, dims=%d)",
        len(all_embeddings),
        settings.EMBEDDING_MODEL,
        settings.EMBEDDING_DIMENSIONS,
    )
    return all_embeddings


def _embed_batch(texts: list[str]) -> list[list[float]]:
    """
    Embed a single batch with retry logic.
    Returns [] on permanent failure (never raises).
    """
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = httpx.post(
                "https://api.openai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.EMBEDDING_MODEL,
                    "input": texts,
                    "dimensions": settings.EMBEDDING_DIMENSIONS,
                },
                timeout=30,
            )

            if resp.status_code == 200:
                data = resp.json()
                # Sort by index — OpenAI does NOT guarantee response order
                sorted_data = sorted(data["data"], key=lambda x: x["index"])
                return [item["embedding"] for item in sorted_data]

            if _should_retry(resp.status_code, attempt):
                delay = _backoff_delay(attempt)
                logger.warning(
                    "Embedding API %d — retrying in %.1fs (attempt %d/%d)",
                    resp.status_code, delay, attempt + 1, _MAX_RETRIES,
                )
                time.sleep(delay)
                continue

            # Deterministic failure — don't retry, return empty
            logger.error(
                "Embedding API permanent failure %d: %s",
                resp.status_code,
                resp.text[:200],
            )
            return []

        except httpx.TimeoutException:
            if attempt < _MAX_RETRIES:
                delay = _backoff_delay(attempt)
                logger.warning(
                    "Embedding timeout — retrying in %.1fs (attempt %d/%d)",
                    delay, attempt + 1, _MAX_RETRIES,
                )
                time.sleep(delay)
                continue
            logger.error("Embedding timed out after all retries")
            return []

        except httpx.ConnectError as exc:
            logger.error("Cannot connect to OpenAI: %s", exc)
            return []

        except Exception as exc:
            logger.error("Unexpected embedding error: %s", exc)
            return []

    return []


def generate_single_embedding(text: str) -> Optional[list[float]]:
    """
    Embed a single text string. Returns None if not configured or failed.
    Used for query-time embedding (resume → query vector for retrieval).
    """
    if not is_configured():
        logger.warning("OPENAI_API_KEY not set — cannot generate query embedding")
        return None

    results = generate_embeddings([text])
    return results[0] if results else None