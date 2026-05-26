"""
FastAPI entry point — Resume Processing + Retrieval Service.

Endpoints:
  POST /analyze    → multipart form: file=<pdf>, user_id=<optional>
                     Parses resume, extracts fields, generates embeddings
  POST /retrieve   → JSON: {query, top_k, filters}
                     Semantic job retrieval from Pinecone
  POST /embed-job  → JSON: {job_id, title, skills, description, metadata}
                     Job ingestion: embed + store in Pinecone
  GET  /health     → liveness probe

WHY FastAPI (not Flask, not Express):
  - Async-first: handles concurrent PDF uploads without blocking
  - Auto-generated OpenAPI docs (free API documentation)
  - Pydantic validation built-in (request validation at the door)
  - Same framework as biomarker service — consistency across services

WHY this is a separate microservice from Node backend:
  - Python has better ML/embedding libraries
  - PDF parsing libraries are Python-native
  - Node backend handles: routing, auth, caching, ranking, queue orchestration
  - Python service handles: extraction, embedding, retrieval
  - Clean separation of concerns

HOW Node backend calls this:
  - BullMQ worker processes SYNC_RESUME job
  - Worker calls POST /analyze with the PDF
  - Gets back structured data + embedding status
  - Stores parsed JSON in Mongo
  - If embeddings failed, re-enqueues for retry
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from pipeline import run_pipeline, run_retrieval

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Resume Pipeline API",
    version="2.0.0",
    description="Resume parsing, embedding, and semantic job retrieval",
)


# Health check
@app.get("/health")
def health():
    """Liveness probe — Render/K8s uses this."""
    from bm25_retriever import get_index_stats
    bm25 = get_index_stats()
    return {
        "status": "ok",
        "service": "resume-pipeline",
        "bm25_jobs_indexed": bm25["document_count"],
    }


# Resume analysis endpoint
@app.post("/analyze")
async def analyze(
    file: UploadFile = File(...),
    user_id: str = Form(default=""),
):
    """
    Process a resume PDF.

    Flow:
      1. Validate PDF
      2. Save to temp file
      3. Run full pipeline (extract → normalize → chunk → embed → store)
      4. Return structured result
      5. Cleanup temp file

    WHY temp file (not in-memory):
      pdfplumber requires file path, not bytes.
      Same approach as biomarker service — proven pattern.

    WHY cleanup in finally:
      If pipeline crashes, temp file still gets deleted.
      No disk leak on repeated failures.
    """
    # Validate PDF
    is_pdf_name = file.filename and file.filename.lower().endswith(".pdf")
    is_pdf_type = file.content_type in (
        "application/pdf",
        "application/octet-stream",
        "binary/octet-stream",
    )

    if not is_pdf_name and not is_pdf_type:
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    # Save to temp file
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        logger.info("Processing resume: %s", file.filename)

        result = run_pipeline(tmp_path, user_id=user_id or None)

        if "error" not in result:
            logger.info(
                "Resume processed: %d skills, %d chunks, embeddings=%s",
                result.get("skill_count", 0),
                result.get("chunk_count", 0),
                result.get("embeddings_generated", False),
            )

    except Exception as exc:
        logger.exception("Pipeline failed")
        return JSONResponse(
            content={"error": f"Internal error: {str(exc)}"},
            status_code=500,
        )
    finally:
        # Cleanup temp file — always, even on crash
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    # Handle pipeline-level errors
    if "error" in result:
        status = 422 if "No skills" in result["error"] else 500
        return JSONResponse(content=result, status_code=status)

    return JSONResponse(content=result, status_code=200)


# Retrieval endpoint
class RetrievalRequest(BaseModel):
    """
    Request body for semantic job retrieval.

    WHY Pydantic model (not raw dict):
      - Validates at the door (bad request → 422, not 500 deep in pipeline)
      - Auto-documents in OpenAPI schema
      - Type safety without manual checking

    UPDATED (Day 31): added candidate_skills + experience_years for ranking.
    """
    query: str
    top_k: int | None = None
    filters: dict | None = None
    # Day 31: Candidate context for ranking
    candidate_skills: list[str] | None = None
    experience_years: float = 0.0
    # Day 30: A/B test flag
    use_hybrid: bool = True


@app.post("/retrieve")
async def retrieve(req: RetrievalRequest):
    """
    Semantic job retrieval — hybrid BM25 + dense, reranked to top 20.

    Updated (Day 30-31):
      - Hybrid retrieval (BM25 + embeddings via RRF)
      - Reranking with skill overlap, experience, quality, recency signals
      - Returns top 20 (not 200) — ranked by final_score

    Called by Node backend's feedService:
      resume embedding → hybrid retrieval → ranked top 20

    Returns job IDs + scores + ranking details.
    Node backend fetches full job data from Mongo.
    """
    if not req.query or len(req.query.strip()) < 10:
        raise HTTPException(
            status_code=400,
            detail="Query text must be at least 10 characters",
        )

    result = run_retrieval(
        query_text                 = req.query,
        top_k                      = req.top_k,
        filters                    = req.filters,
        candidate_skills           = req.candidate_skills,
        candidate_experience_years = req.experience_years,
        use_hybrid                 = req.use_hybrid,
    )

    if "error" in result and not result.get("matches"):
        return JSONResponse(content=result, status_code=500)

    return JSONResponse(content=result, status_code=200)


# Job embedding endpoint
class JobEmbedRequest(BaseModel):
    """
    Request body for job embedding ingestion.

    WHY separate endpoint (not inline in Node):
      - Embedding logic lives in Python (OpenAI SDK, vector math)
      - Node backend calls this via BullMQ worker (async, retriable)
      - Same microservice boundary as resume processing
    """
    job_id: str
    title: str
    skills: list[str] = []
    description: str = ""
    metadata: dict = {}


@app.post("/embed-job")
async def embed_job(req: JobEmbedRequest):
    """
    Job ingestion pipeline:
      title + skills + description → embedding → Pinecone

    Called when recruiter creates/updates a job.
    BullMQ worker in Node backend triggers this.

    IMPORTANT: embeds title + skills + description together.
    NOT just title. This captures full job semantics.
    """
    # Combine fields for embedding (architecture doc requirement)
    embed_text = f"{req.title}. Skills: {', '.join(req.skills)}"
    if req.description:
        embed_text += f". {req.description[:500]}"

    try:
        from embedder import generate_embeddings
        from retriever import upsert_job_embeddings

        embeddings = generate_embeddings([embed_text])

        upsert_job_embeddings(
            job_id=req.job_id,
            embeddings=embeddings,
            metadata={
                "title": req.title,
                "skills": req.skills[:20],  # Pinecone metadata size limit
                **req.metadata,
            },
        )

        # ── Also index in BM25 (Day 30) ───────────────────────────────────
        # WHY here (not in a separate call): the BM25 index needs the same data
        # as Pinecone. Doing it atomically in the same endpoint ensures the two
        # indexes stay in sync — a job always appears in both or neither.
        from bm25_retriever import index_job
        index_job(
            job_id      = req.job_id,
            title       = req.title,
            skills      = req.skills,
            description = req.description,
        )

        return JSONResponse(
            content={
                "job_id": req.job_id,
                "embedded": True,
                "vector_count": len(embeddings),
                "bm25_indexed": True,
            },
            status_code=200,
        )

    except Exception as exc:
        logger.exception("Job embedding failed")
        return JSONResponse(
            content={"error": str(exc), "job_id": req.job_id, "embedded": False},
            status_code=500,
        )


# Quality scoring endpoint (Day 33)
class QualityScoreRequest(BaseModel):
    job_id: str
    title: str
    skills: list[str] = []
    description: str = ""


@app.post("/score-job-quality")
async def score_job_quality(req: QualityScoreRequest):
    """
    Score a job posting for quality using LLM evaluation.

    Called when a job is created or updated.
    Returns a quality_score [0, 1] + dimension breakdown.
    Score is stored in MongoDB by the Node backend and passed to Pinecone
    metadata on next upsert — used by ranker as a ranking signal.

    WHY a separate endpoint (not inline in embed-job):
      Quality scoring takes 1-3s (LLM call). Embedding is ~200ms.
      Separating allows Node backend to:
        - Embed synchronously (fast, blocking)
        - Quality score asynchronously (slow, via BullMQ worker)
      This is the same pattern as the async embedding queue in Day 34.
    """
    from quality_scorer import score_job_quality as _score

    result = _score(
        job_id      = req.job_id,
        title       = req.title,
        skills      = req.skills,
        description = req.description,
    )
    return JSONResponse(content=result, status_code=200)


# "Why this job" explanation endpoint (Day 32)
class ExplainRequest(BaseModel):
    job_data: dict           # {title, skills, description}
    candidate_data: dict     # {skills, experience_years, domain_coverage}
    ranking_details: dict    # from ranker.rerank() output


@app.post("/explain-match")
async def explain_match(req: ExplainRequest):
    """
    Generate a human-readable explanation of why a job matches a candidate.

    RAG pattern: LLM generates explanation GROUNDED in retrieval data.
    LLM does not decide what's relevant — it only explains what our
    structured ranking system already computed.

    Called by Node backend when user taps "Why this job?" on a match.
    Not called automatically for all 20 results — lazy on demand.
    """
    from explainer import explain_match as _explain

    explanation = _explain(
        job_data        = req.job_data,
        candidate_data  = req.candidate_data,
        ranking_details = req.ranking_details,
    )
    return JSONResponse(content={"explanation": explanation}, status_code=200)


# Debug / analytics endpoint (Day 35)
@app.get("/debug/retrieval-stats")
async def retrieval_debug_stats():
    """
    Retrieval system health and performance stats.

    Returns:
      - BM25 index stats (document count, term count, avg doc length)
      - Retrieval cache stats (hit rate, size, TTL)
      - Config snapshot (alpha, top_k, rerank_k)

    WHY this endpoint exists:
      Debugging retrieval quality requires knowing system state.
      "Why is job X ranked #5 and not #1?" starts with understanding
      what signals the system has available.

      This is the observability layer — same principle as metrics dashboards
      in production systems. You can't improve what you can't measure.
    """
    from bm25_retriever import get_index_stats
    from retriever import get_cache_stats
    from config import settings

    return JSONResponse(content={
        "bm25_index":       get_index_stats(),
        "retrieval_cache":  get_cache_stats(),
        "config": {
            "hybrid_alpha":     settings.HYBRID_ALPHA,
            "top_k_retrieval":  settings.TOP_K_RETRIEVAL,
            "top_k_rerank":     settings.TOP_K_RERANK,
            "cache_ttl_secs":   settings.RETRIEVAL_CACHE_TTL_SECONDS,
            "min_quality_score": settings.MIN_QUALITY_SCORE,
        },
    }, status_code=200)


@app.post("/debug/clear-cache")
async def clear_retrieval_cache():
    """
    Clear the retrieval cache. Use after bulk job updates.
    Exposed as endpoint so Node backend can trigger it without restarting service.
    """
    from retriever import clear_retrieval_cache as _clear
    _clear()
    return JSONResponse(content={"cleared": True}, status_code=200)


# Render-compatible entry point
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)