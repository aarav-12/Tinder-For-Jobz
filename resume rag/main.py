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


# ─────────────────────────────────────────────────────────────────────────────
# Health check
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    """Liveness probe — Render/K8s uses this."""
    return {"status": "ok", "service": "resume-pipeline"}


# ─────────────────────────────────────────────────────────────────────────────
# Resume analysis endpoint
# ─────────────────────────────────────────────────────────────────────────────
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


# ─────────────────────────────────────────────────────────────────────────────
# Retrieval endpoint
# ─────────────────────────────────────────────────────────────────────────────
class RetrievalRequest(BaseModel):
    """
    Request body for semantic job retrieval.

    WHY Pydantic model (not raw dict):
      - Validates at the door (bad request → 422, not 500 deep in pipeline)
      - Auto-documents in OpenAPI schema
      - Type safety without manual checking
    """
    query: str
    top_k: int | None = None
    filters: dict | None = None


@app.post("/retrieve")
async def retrieve(req: RetrievalRequest):
    """
    Semantic job retrieval.

    Called by Node backend's feedService:
      resume embedding → Pinecone ANN → top-K job matches

    Returns job IDs + similarity scores.
    Node backend fetches full job data from Mongo.
    """
    if not req.query or len(req.query.strip()) < 10:
        raise HTTPException(
            status_code=400,
            detail="Query text must be at least 10 characters",
        )

    result = run_retrieval(req.query, top_k=req.top_k, filters=req.filters)

    if "error" in result and not result.get("matches"):
        return JSONResponse(content=result, status_code=500)

    return JSONResponse(content=result, status_code=200)


# ─────────────────────────────────────────────────────────────────────────────
# Job embedding endpoint
# ─────────────────────────────────────────────────────────────────────────────
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

        return JSONResponse(
            content={
                "job_id": req.job_id,
                "embedded": True,
                "vector_count": len(embeddings),
            },
            status_code=200,
        )

    except Exception as exc:
        logger.exception("Job embedding failed")
        return JSONResponse(
            content={"error": str(exc), "job_id": req.job_id, "embedded": False},
            status_code=500,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Render-compatible entry point
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)