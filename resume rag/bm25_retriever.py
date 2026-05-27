"""
BM25 sparse retrieval — keyword-based scoring for resume-to-job matching.

WHY BM25 (not TF-IDF, not plain keyword count):
─────────────────────────────────────────────
  PROBLEM: imagine you have 1000 job postings. Some say "Python" once.
  Some say "Python" 20 times. A job that says "Python" 20 times is NOT
  20x better than one that says it once. TF-IDF doesn't handle this well.

  BM25 SOLVES THIS with two parameters:
    k1 = term saturation: after a word appears ~5 times, score barely increases.
         "Python Python Python... Python" = not much better than "Python" twice.
    b  = length normalization: a long job description with 1 mention of "Python"
         should score LESS than a short, focused listing with 1 mention.
         Because the short one is MORE about Python.

  BM25 is the backbone of Elasticsearch, Lucene, and Solr.
  It's been THE standard sparse retrieval method since 1994.
  We're using it because it handles skill keywords perfectly.

WHY sparse retrieval at all (we already have embeddings):
─────────────────────────────────────────────────────────
  PROBLEM: imagine a job requires "Kubernetes". A candidate with
  "Docker, k8s, container orchestration" has a perfect semantic embedding match.
  BUT another candidate who listed "Kubernetes" literally might score HIGHER
  in embeddings (exact token match) yet the first candidate is equally qualified.

  Dense (embedding) retrieval: great at MEANING
  Sparse (BM25) retrieval: great at EXACT KEYWORDS
  Hybrid: best of both worlds.

  Real example where dense ALONE fails:
    Job: "needs Python 3.11"
    Resume A: "Python 3.11, FastAPI, async" → dense score 0.91, BM25 score 8.4
    Resume B: "programming, automation, scripting" → dense score 0.88, BM25 score 0.0
    Resume A is clearly better. Dense alone barely separates them.

HOW BM25 WORKS (simple explanation):
──────────────────────────────────────
  score(query, doc) = sum over each query term:
    IDF(term) * (tf * (k1+1)) / (tf + k1 * (1 - b + b * doc_len / avg_len))

  IDF = how rare is this word across all docs? "Python" everywhere = low IDF.
        "Kubernetes" rarely = high IDF. Rare words matter more.
  TF  = how often does term appear in this doc?
  The denominator = saturation + length normalization.

ARCHITECTURE DECISION — IN-MEMORY BM25 INDEX:
──────────────────────────────────────────────
  We store the BM25 index in memory (not Redis, not a separate service).
  WHY: BM25 index for 10k jobs fits in ~50MB RAM. Fast to rebuild.
  Pinecone = dense vectors. BM25 = in-memory sparse index.
  They serve different purposes and don't need to be unified.

  REBUILD STRATEGY: index rebuilds when:
    - Service starts (from a corpus dump if available)
    - A new job is added via add_document()
  For Day 34+ we'll add background rebuild workers.
"""

from __future__ import annotations

import logging
import math
import re
import string
from collections import Counter, defaultdict
from typing import Optional

logger = logging.getLogger(__name__)

# ── BM25 hyperparameters ──────────────────────────────────────────────────────
# k1: term frequency saturation. 1.2–2.0 is standard range.
# We use 1.5 — middle ground. Higher = rewards term repetition more.
_K1 = 1.5
# b: length normalization. 0 = no normalization, 1 = full normalization.
# 0.75 is the classic default from the original BM25 paper.
_B = 0.75

# ── Stopwords — words that carry no meaning for job matching ─────────────────
# WHY NOT use NLTK stopwords: no extra dependency.
# This list is sufficient for job/resume domain.
_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
    "for", "of", "with", "by", "from", "is", "are", "was", "were",
    "be", "been", "being", "have", "has", "had", "do", "does", "did",
    "will", "would", "could", "should", "may", "might", "shall",
    "not", "no", "nor", "so", "yet", "both", "either", "neither",
    "each", "any", "all", "both", "few", "more", "most", "other",
    "some", "such", "than", "too", "very", "can", "just", "this",
    "that", "these", "those", "i", "you", "we", "they", "it",
    "experience", "skills", "team", "work", "working", "using",
    "use", "used", "years", "year", "strong", "good", "ability",
    "knowledge", "understanding", "proficient", "familiar",
})


def _tokenize(text: str) -> list[str]:
    """
    Convert text into a list of meaningful tokens.

    Strategy:
      1. Lowercase
      2. Replace punctuation with spaces (keep hyphens inside words: "ci-cd")
      3. Split on whitespace
      4. Remove stopwords + very short tokens

    WHY keep hyphens inside words:
      "ci-cd", "full-stack", "real-time" are single skill tokens.
      Splitting them loses meaning.

    WHY not stemming:
      "designing" → "design" via stemming. But resume text uses both.
      In practice, for a tech skills domain, stemming adds complexity
      with minimal gain. Keeping it simple.
    """
    text = text.lower()
    # Replace non-alphanumeric (except hyphens between words) with space
    text = re.sub(r"[^\w\s\-]", " ", text)
    # Collapse multiple spaces
    text = re.sub(r"\s+", " ", text).strip()

    tokens = []
    for token in text.split():
        # Remove leading/trailing hyphens
        token = token.strip("-")
        if len(token) < 2:
            continue
        if token in _STOPWORDS:
            continue
        tokens.append(token)

    return tokens


class BM25Index:
    """
    In-memory BM25 index for job documents.

    DESIGN PRINCIPLES:
      1. Single Responsibility: this class ONLY does BM25 scoring.
         It doesn't know about Pinecone, embeddings, or the pipeline.
      2. Immutable after build: add_document() appends; no deletes mid-use.
         For deletes: rebuild index (fast enough for < 50k docs).
      3. Never raises: score_query() returns {} on any failure.
         Retrieval degradation is graceful, not a crash.

    Internal state:
      _docs:       {doc_id: [tokens]}  — token lists for each doc
      _tf:         {doc_id: {term: count}}  — term frequency per doc
      _df:         {term: int}  — document frequency (how many docs have this term)
      _avg_len:    float — average doc length (tokens)
      _N:          int — total number of docs
    """

    def __init__(self) -> None:
        self._docs:    dict[str, list[str]] = {}
        self._tf:      dict[str, Counter] = {}
        self._df:      Counter = Counter()
        self._avg_len: float = 0.0
        self._N:       int = 0

    def add_document(self, doc_id: str, text: str) -> None:
        """
        Add a document to the index.

        IMPORTANT: updates _df and _avg_len incrementally.
        WHY incremental: rebuilding the entire index on every job add
        would be O(N) per insert. Incremental is O(1) per insert.

        NOTE: doc_id should match the job_id used in Pinecone.
        This is how hybrid_retriever.py combines BM25 scores with
        dense scores — same ID space.
        """
        tokens = _tokenize(text)
        if not tokens:
            logger.warning("Document %s produced no tokens — skipping", doc_id)
            return

        # Update term frequency for this doc
        self._docs[doc_id] = tokens
        self._tf[doc_id] = Counter(tokens)

        # Update document frequency for each UNIQUE term in this doc
        for term in set(tokens):
            self._df[term] += 1

        # Update running average doc length
        # WHY running average: avoids storing all lengths separately.
        # Formula: new_avg = old_avg + (new_len - old_avg) / new_N
        self._N += 1
        self._avg_len += (len(tokens) - self._avg_len) / self._N

        logger.debug("BM25 index: added doc %s (%d tokens)", doc_id, len(tokens))

    def score_query(self, query: str, top_k: int = 200) -> dict[str, float]:
        """
        Score all documents against a query. Returns top_k {doc_id: score}.

        Returns {} if index is empty or query has no meaningful tokens.
        NEVER raises.

        COMPLEXITY: O(N * Q) where N = docs, Q = query terms.
        For 10k jobs and 20-word query: 200k operations — ~20ms. Fine.
        For 100k jobs: ~200ms. At that scale, switch to Elasticsearch.
        """
        if self._N == 0:
            logger.warning("BM25 index is empty — no jobs indexed yet")
            return {}

        query_tokens = _tokenize(query)
        if not query_tokens:
            return {}

        scores: dict[str, float] = defaultdict(float)

        for term in query_tokens:
            # IDF calculation with smoothing to avoid log(0)
            # Standard Robertson-Sparck Jones IDF with +0.5 smoothing:
            # IDF = log((N - df + 0.5) / (df + 0.5) + 1)
            df = self._df.get(term, 0)
            if df == 0:
                continue  # Term not in any document — skip

            idf = math.log((self._N - df + 0.5) / (df + 0.5) + 1)

            for doc_id, tf_counter in self._tf.items():
                tf = tf_counter.get(term, 0)
                if tf == 0:
                    continue

                doc_len = len(self._docs[doc_id])

                # BM25 term score:
                numerator   = tf * (_K1 + 1)
                denominator = tf + _K1 * (1 - _B + _B * doc_len / self._avg_len)
                scores[doc_id] += idf * (numerator / denominator)

        if not scores:
            return {}

        # Sort by score descending, return top_k
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return dict(sorted_scores[:top_k])

    def remove_document(self, doc_id: str) -> None:
        """
        Remove a document from the index.

        WHY this is expensive: we must decrement _df for all terms.
        For production at scale, use a "tombstone" strategy (mark deleted,
        rebuild periodically). For now: correct but O(unique_terms).
        """
        if doc_id not in self._docs:
            return

        tokens = self._docs.pop(doc_id)
        self._tf.pop(doc_id, None)

        # Decrement document frequency
        for term in set(tokens):
            if term in self._df:
                self._df[term] -= 1
                if self._df[term] <= 0:
                    del self._df[term]

        # Recompute avg_len — simpler than incremental subtract
        if self._N > 1:
            total_tokens = sum(len(t) for t in self._docs.values())
            self._N -= 1
            self._avg_len = total_tokens / self._N
        else:
            self._N = 0
            self._avg_len = 0.0

    @property
    def document_count(self) -> int:
        return self._N

    def is_empty(self) -> bool:
        return self._N == 0


# ── Module-level singleton index ─────────────────────────────────────────────
# WHY singleton: one index per service instance.
# Multiple instances of BM25Index would get out of sync.
# For multi-worker Uvicorn: each worker has its own copy (acceptable for
# read-heavy workload; jobs are added rarely vs queried constantly).
_JOB_INDEX = BM25Index()


def index_job(job_id: str, title: str, skills: list[str], description: str = "") -> None:
    """
    Add a job to the BM25 index. Called when job is created/updated.

    Text format: title + skills + description combined.
    WHY combine: same logic as the dense embedding text in embed-job endpoint.
    Consistent text representation across sparse AND dense retrieval.
    """
    text = f"{title} {' '.join(skills)} {description}"
    _JOB_INDEX.add_document(job_id, text)
    logger.info(
        "Indexed job %s in BM25 (%d total jobs indexed)",
        job_id,
        _JOB_INDEX.document_count,
    )


def search_jobs_bm25(query: str, top_k: int = 200) -> dict[str, float]:
    """
    BM25 search over indexed jobs.

    Returns {job_id: bm25_score} for top_k results.
    Scores are raw BM25 values (not normalized — normalization
    happens in hybrid_retriever.py during fusion).
    """
    return _JOB_INDEX.score_query(query, top_k=top_k)


def remove_job(job_id: str) -> None:
    """Remove a job from the BM25 index (when job is deleted)."""
    _JOB_INDEX.remove_document(job_id)


def get_index_stats() -> dict:
    """Return index stats for health checks and debugging."""
    return {
        "document_count": _JOB_INDEX.document_count,
        "term_count": len(_JOB_INDEX._df),
        "avg_doc_length": round(_JOB_INDEX._avg_len, 1),
    }