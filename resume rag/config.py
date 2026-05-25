"""
Centralized configuration — single source of truth for all settings.

WHY pydantic-settings:
  - Validates env vars at startup (fail fast, not at request time)
  - Type coercion built-in (str → int, str → float)
  - .env file support without python-dotenv boilerplate
  - Default values for local dev, overrides via env in production

WHY every setting is here:
  - No magic strings scattered across files
  - One place to audit what the service depends on
  - Easy to see what needs configuring when deploying
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── OpenAI Embeddings ─────────────────────────────────────────────────
    # WHY OpenAI: production-quality embeddings, simplest integration,
    # consistent dimensionality (1536 for text-embedding-3-small)
    OPENAI_API_KEY: str = ""
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSIONS: int = 1536

    # ── Pinecone Vector DB ────────────────────────────────────────────────
    # WHY Pinecone: managed ANN, no infra to maintain, metadata filtering
    # built-in, scales without DevOps overhead
    PINECONE_API_KEY: str = ""
    PINECONE_INDEX_NAME: str = "job-embeddings"
    PINECONE_ENVIRONMENT: str = "us-east-1"

    # ── Retrieval settings ────────────────────────────────────────────────
    # WHY 200: retrieve many, rank few — gives rankingService enough
    # candidates for behavioral reranking + keyword boosting
    TOP_K_RETRIEVAL: int = 200

    # ── LLM fallback (Ollama — local dev, or for scanned/messy resumes) ──
    OLLAMA_URL: str = "http://localhost:11434"
    LLM_MODEL: str = "llama3"
    LLM_TEMPERATURE: float = 0.0       # deterministic extraction
    LLM_NUM_PREDICT: int = 2048        # resumes can be dense

    # ── Pipeline thresholds ───────────────────────────────────────────────
    MIN_SKILLS: int = 3                # warn if fewer skills extracted
    MIN_SECTIONS: int = 2              # warn if fewer sections parsed
    MAX_CHUNK_CHARS: int = 1000        # per-chunk character limit
    BATCH_SIZE: int = 20               # embeddings per API call

    class Config:
        env_file = ".env"
        extra = "ignore"                # don't crash on unknown env vars


settings = Settings()
