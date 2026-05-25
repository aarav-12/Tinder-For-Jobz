"""
Semantic chunking — splits structured resume data into embeddable chunks.

WHY chunking matters:
  A full resume embedding dilutes meaning.
  "Python + 5 years backend + MS CS Stanford" as one vector
  becomes a blurry average that matches poorly against specific jobs.

  Separate chunks:
    skills chunk    → matches "need Python, React, Docker"
    experience chunk → matches "5+ years backend engineer"
    education chunk  → matches "MS Computer Science"

  This is retrieval-quality architecture, not just storage architecture.

WHY NOT LangChain recursive splitting:
  - Resumes have natural semantic boundaries (sections)
  - Recursive character splitting cuts mid-sentence
  - Our extractor already gives us structured sections
  - No dependency = no complexity = no debugging LangChain internals

Chunk format:
  {
    "text": str,           # embeddable text content
    "type": str,           # "skills" | "experience" | "education" | "projects" | "summary"
    "metadata": dict,      # section-specific metadata for filtering
  }

MAX_CHUNK_CHARS:
  Enforced per chunk. If a section exceeds limit, it gets split
  at sentence boundaries (not mid-word like recursive splitting).
"""

from __future__ import annotations

import logging
import re

from config import settings

logger = logging.getLogger(__name__)


def _split_at_boundary(text: str, max_chars: int) -> list[str]:
    """
    Split text at sentence boundaries if it exceeds max_chars.

    WHY sentence boundaries (not character count):
      "...built distributed sys" is garbage for embedding.
      "...built distributed systems at scale." preserves meaning.

    Fallback: if a single sentence exceeds max_chars, split on newlines.
    """
    if len(text) <= max_chars:
        return [text]

    # Split on sentence-ending punctuation
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks = []
    current = ""

    for sentence in sentences:
        if len(current) + len(sentence) + 1 > max_chars and current:
            chunks.append(current.strip())
            current = sentence
        else:
            current = current + " " + sentence if current else sentence

    if current.strip():
        chunks.append(current.strip())

    return chunks if chunks else [text[:max_chars]]


def chunk_resume(extracted: dict) -> list[dict]:
    """
    Convert structured extraction output into embeddable chunks.

    Input: output of extractor.extract_resume()
    Output: list of {"text": str, "type": str, "metadata": dict}

    IMPORTANT DECISION: each chunk type gets different text formatting
    because embeddings encode meaning from text structure.
    "Skills: Python, React, Docker" embeds differently than
    "Python React Docker" — the label helps the embedding model
    understand this is a skill list, not random words.
    """
    chunks: list[dict] = []
    max_chars = settings.MAX_CHUNK_CHARS

    # ── Skills chunk ──────────────────────────────────────────────────────
    skills = extracted.get("skills", [])
    if skills:
        skills_text = "Technical Skills: " + ", ".join(skills)
        for part in _split_at_boundary(skills_text, max_chars):
            chunks.append({
                "text": part,
                "type": "skills",
                "metadata": {
                    "skill_count": len(skills),
                    "skills_list": skills[:50],  # cap for Pinecone metadata limit
                },
            })

    # ── Experience chunks (one per job) ───────────────────────────────────
    # WHY one chunk per job:
    #   "5 years at Google doing ML" and "2 years at startup doing frontend"
    #   are completely different signals. Merging dilutes both.
    experience = extracted.get("experience", [])
    for i, exp in enumerate(experience):
        exp_text = (
            f"{exp.get('title', 'Role')} at {exp.get('company', 'Company')}"
        )
        if exp.get("duration"):
            exp_text += f" ({exp['duration']})"
        if exp.get("description"):
            exp_text += f". {exp['description']}"

        for part in _split_at_boundary(exp_text, max_chars):
            chunks.append({
                "text": part,
                "type": "experience",
                "metadata": {
                    "title": exp.get("title", ""),
                    "company": exp.get("company", ""),
                    "duration": exp.get("duration", ""),
                    "position_index": i,
                },
            })

    # ── Education chunks ──────────────────────────────────────────────────
    education = extracted.get("education", [])
    if education:
        edu_parts = []
        for edu in education:
            line = edu.get("degree", "")
            if edu.get("institution"):
                line += f" from {edu['institution']}"
            if edu.get("year"):
                line += f" ({edu['year']})"
            edu_parts.append(line)

        edu_text = "Education: " + "; ".join(edu_parts)
        for part in _split_at_boundary(edu_text, max_chars):
            chunks.append({
                "text": part,
                "type": "education",
                "metadata": {
                    "degrees": [e.get("degree", "") for e in education],
                },
            })

    # ── Project chunks (one per project) ──────────────────────────────────
    projects = extracted.get("projects", [])
    for proj in projects:
        proj_text = f"Project: {proj.get('name', '')}"
        if proj.get("description"):
            proj_text += f". {proj['description']}"
        if proj.get("tech"):
            proj_text += f". Technologies: {', '.join(proj['tech'])}"

        for part in _split_at_boundary(proj_text, max_chars):
            chunks.append({
                "text": part,
                "type": "projects",
                "metadata": {
                    "project_name": proj.get("name", ""),
                    "tech": proj.get("tech", []),
                },
            })

    # ── Summary chunk ─────────────────────────────────────────────────────
    summary = extracted.get("summary", "")
    if summary and len(summary.strip()) > 20:
        for part in _split_at_boundary(summary, max_chars):
            chunks.append({
                "text": part,
                "type": "summary",
                "metadata": {},
            })

    # ── Composite chunk (skills + latest role) ────────────────────────────
    # WHY a composite chunk:
    #   Pinecone retrieval matches against job descriptions that say
    #   "React developer with 3+ years experience". Neither skills chunk
    #   alone nor experience chunk alone captures this — but a composite does.
    if skills and experience:
        latest = experience[0]
        composite = (
            f"{latest.get('title', 'Developer')} with skills in "
            f"{', '.join(skills[:10])}"
        )
        if latest.get("company"):
            composite += f". Currently/previously at {latest['company']}"

        chunks.append({
            "text": composite,
            "type": "composite",
            "metadata": {
                "is_composite": True,
            },
        })

    logger.info(
        "Chunked resume into %d chunks (skills=%d, exp=%d, edu=%d, proj=%d)",
        len(chunks),
        sum(1 for c in chunks if c["type"] == "skills"),
        sum(1 for c in chunks if c["type"] == "experience"),
        sum(1 for c in chunks if c["type"] == "education"),
        sum(1 for c in chunks if c["type"] == "projects"),
    )

    return chunks