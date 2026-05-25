"""
Resume field extractor — pulls structured data from raw resume text.

Architecture mirrors biomarker extractor.py:
  1. Regex/heuristic parser  — fast, deterministic, handles clean resumes
  2. LLM fallback (Ollama)   — handles messy/scanned/non-standard layouts

WHY this layered approach:
  - Regex is fast + free (no API cost)
  - LLM is slow + expensive but handles edge cases
  - Deterministic results always win over LLM on conflicts (same as biomarker _merge)

WHY NOT just use LLM for everything:
  - Latency: 200ms regex vs 3-5s LLM call
  - Cost: $0 vs tokens per request
  - Reliability: regex is deterministic, LLM can hallucinate skills

Output format:
  {
    "skills": ["Python", "React", ...],
    "experience": [{"title": str, "company": str, "duration": str, "description": str}],
    "education": [{"degree": str, "institution": str, "year": str}],
    "projects": [{"name": str, "description": str, "tech": [str]}],
    "summary": str,
    "contact": {"name": str, "email": str, "phone": str, "location": str}
  }

Node backend receives this raw extraction. Normalization happens downstream.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from config import settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Section detection patterns
# ─────────────────────────────────────────────────────────────────────────────
# WHY regex for section headers:
#   Resumes follow predictable section naming conventions.
#   "Experience", "WORK EXPERIENCE", "Employment History" — all mean the same thing.
#   Regex catches these variants cheaply.

_SECTION_PATTERNS: dict[str, re.Pattern] = {
    "experience": re.compile(
        r"^(?:work\s+)?(?:experience|employment|professional\s+(?:experience|history)|career\s+history)",
        re.IGNORECASE | re.MULTILINE,
    ),
    "education": re.compile(
        r"^(?:education|academic|qualifications|degrees?)",
        re.IGNORECASE | re.MULTILINE,
    ),
    "skills": re.compile(
        r"^(?:(?:technical\s+)?skills|technologies|competencies|expertise|tech\s+stack|proficiencies)",
        re.IGNORECASE | re.MULTILINE,
    ),
    "projects": re.compile(
        r"^(?:projects?|personal\s+projects?|portfolio|side\s+projects?|notable\s+projects?)",
        re.IGNORECASE | re.MULTILINE,
    ),
    "summary": re.compile(
        r"^(?:summary|objective|about\s+me|professional\s+summary|profile|career\s+objective)",
        re.IGNORECASE | re.MULTILINE,
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# Contact extraction
# ─────────────────────────────────────────────────────────────────────────────
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(
    r"(?:\+?\d{1,3}[\s\-]?)?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{4}"
)
# Location: "City, State" or "City, Country" — stops at pipe/newline
_LOCATION_RE = re.compile(
    r"([A-Z][a-z]+(?:\s[A-Z][a-z]+)*),\s*([A-Z]{2}|[A-Z][a-z]+(?:\s[A-Z][a-z]+)*)(?=\s*[|\n]|$)"
)


def _extract_contact(text: str) -> dict[str, str]:
    """Pull contact info from the first ~500 chars (usually header area)."""
    header = text[:500]
    lines = header.strip().splitlines()

    email_m = _EMAIL_RE.search(header)
    phone_m = _PHONE_RE.search(header)

    # Search for location line-by-line to avoid cross-line matches
    location = ""
    for line in lines[:8]:  # location is in first few lines
        loc_m = _LOCATION_RE.search(line)
        if loc_m:
            location = loc_m.group(0).strip()
            break

    # Name heuristic: first non-empty line that isn't an email/phone/url
    name = ""
    for line in lines:
        line = line.strip()
        if not line or len(line) < 2:
            continue
        if _EMAIL_RE.search(line) and len(line) < 50:
            continue
        if _PHONE_RE.match(line):
            continue
        if line.startswith("http"):
            continue
        name = line
        break

    return {
        "name": name,
        "email": email_m.group(0) if email_m else "",
        "phone": phone_m.group(0) if phone_m else "",
        "location": location,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Section splitting
# ─────────────────────────────────────────────────────────────────────────────
def _split_sections(text: str) -> dict[str, str]:
    """
    Split resume text into named sections.

    WHY this approach:
      - Find all section header positions
      - Sort by position
      - Extract text between consecutive headers
      - Anything before first header = "header" (contact info area)

    Loophole solved:
      If no sections detected at all, return entire text as "raw"
      so downstream doesn't silently drop the whole resume.
    """
    markers: list[tuple[int, str]] = []

    for section_name, pattern in _SECTION_PATTERNS.items():
        for match in pattern.finditer(text):
            markers.append((match.start(), section_name))

    if not markers:
        logger.warning("No section headers detected — returning raw text")
        return {"raw": text}

    # Sort by position in document
    markers.sort(key=lambda x: x[0])

    sections: dict[str, str] = {}

    # Text before first section = header/contact area
    if markers[0][0] > 0:
        sections["header"] = text[: markers[0][0]].strip()

    # Extract each section's content
    for i, (pos, name) in enumerate(markers):
        # Find end of section header line
        header_end = text.find("\n", pos)
        if header_end == -1:
            header_end = pos

        # Content runs until next section or end of text
        if i + 1 < len(markers):
            content = text[header_end:markers[i + 1][0]]
        else:
            content = text[header_end:]

        sections[name] = content.strip()

    return sections


# ─────────────────────────────────────────────────────────────────────────────
# Skills extraction
# ─────────────────────────────────────────────────────────────────────────────
# Common delimiter patterns in skill lists
_SKILL_DELIMITERS = re.compile(r"[,|•·▪▸►●○◦\n]")
# Junk that slips into skill lists
_SKILL_JUNK = re.compile(
    r"^(and|or|etc|proficient|experienced|familiar|with|in|strong|expert|good)$",
    re.IGNORECASE,
)


def _extract_skills(skills_text: str) -> list[str]:
    """
    Parse skill list from skills section text.

    WHY split on multiple delimiters:
      Resumes use commas, bullets, pipes, newlines — no standard format.
      Splitting on all common separators catches most layouts.

    Loophole: strips whitespace + drops single-char junk,
    which prevents "," or "•" from becoming a "skill".
    """
    if not skills_text:
        return []

    raw_skills = _SKILL_DELIMITERS.split(skills_text)
    cleaned = []
    seen = set()

    for skill in raw_skills:
        skill = skill.strip().strip("-").strip()
        # Drop too short, too long, pure junk
        if len(skill) < 2 or len(skill) > 60:
            continue
        if _SKILL_JUNK.match(skill):
            continue
        # Deduplicate (case-insensitive)
        key = skill.lower()
        if key not in seen:
            seen.add(key)
            cleaned.append(skill)

    return cleaned


# ─────────────────────────────────────────────────────────────────────────────
# Experience extraction
# ─────────────────────────────────────────────────────────────────────────────
# Pattern: "Software Engineer at Google" or "Software Engineer | Google"
_ROLE_LINE_RE = re.compile(
    r"^(.+?)\s+(?:at|@|[|–—-])\s+(.+?)(?:\s*[|–—-]\s*(.+))?$",
    re.IGNORECASE,
)
# Date range: "Jan 2020 - Present", "2019 – 2021", "March 2018 - Dec 2020"
_DATE_RANGE_RE = re.compile(
    r"(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+)?\d{4}"
    r"\s*[-–—]\s*"
    r"(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+)?"
    r"(?:\d{4}|[Pp]resent|[Cc]urrent)",
    re.IGNORECASE,
)


def _extract_experience(exp_text: str) -> list[dict]:
    """
    Extract job entries from experience section.

    WHY heuristic-based (not LLM):
      Most resumes follow: Title — Company — Date — Bullets pattern.
      Regex catches 80%+ of standard formats for free.
    """
    if not exp_text:
        return []

    entries = []
    lines = exp_text.strip().splitlines()
    current: dict[str, Any] | None = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        role_m = _ROLE_LINE_RE.match(line)
        date_m = _DATE_RANGE_RE.search(line)

        if role_m:
            # New job entry
            if current:
                entries.append(current)
            current = {
                "title": role_m.group(1).strip(),
                "company": role_m.group(2).strip(),
                "duration": role_m.group(3).strip() if role_m.group(3) else "",
                "description": "",
            }
        elif date_m and current and not current.get("duration"):
            current["duration"] = date_m.group(0).strip()
        elif current:
            # Accumulate description bullets
            bullet = line.lstrip("-•·▪▸►● ")
            if bullet:
                if current["description"]:
                    current["description"] += " " + bullet
                else:
                    current["description"] = bullet

    if current:
        entries.append(current)

    return entries


# ─────────────────────────────────────────────────────────────────────────────
# Education extraction
# ─────────────────────────────────────────────────────────────────────────────
_DEGREE_RE = re.compile(
    r"(B\.?S\.?|B\.?A\.?|M\.?S\.?|M\.?A\.?|Ph\.?D\.?|MBA|B\.?Tech|M\.?Tech|"
    r"Bachelor|Master|Doctor|Associate|Diploma)",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"20\d{2}|19\d{2}")


def _extract_education(edu_text: str) -> list[dict]:
    """Extract education entries — degree, institution, year."""
    if not edu_text:
        return []

    entries = []
    lines = edu_text.strip().splitlines()

    for line in lines:
        line = line.strip()
        if not line or len(line) < 5:
            continue

        degree_m = _DEGREE_RE.search(line)
        year_m = _YEAR_RE.search(line)

        if degree_m:
            entries.append({
                "degree": line.strip(),
                "institution": "",   # often on same line, hard to split reliably
                "year": year_m.group(0) if year_m else "",
            })

    return entries


# ─────────────────────────────────────────────────────────────────────────────
# Projects extraction
# ─────────────────────────────────────────────────────────────────────────────
def _extract_projects(proj_text: str) -> list[dict]:
    """Extract project entries from projects section."""
    if not proj_text:
        return []

    entries = []
    lines = proj_text.strip().splitlines()
    current: dict[str, Any] | None = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Project names are usually short lines without bullets
        # But skip lines that look like description fragments (commas, "and", "with")
        is_desc_fragment = bool(re.search(r",\s+and\s+|,\s+with\s+|^\w+\.\s*$", line, re.IGNORECASE))
        if len(line) < 60 and not line.startswith(("-", "•", "·")) and not is_desc_fragment:
            if current:
                entries.append(current)
            current = {
                "name": line,
                "description": "",
                "tech": [],
            }
        elif current:
            bullet = line.lstrip("-•·▪▸►● ")
            if current["description"]:
                current["description"] += " " + bullet
            else:
                current["description"] = bullet

    if current:
        entries.append(current)

    return entries


# ─────────────────────────────────────────────────────────────────────────────
# LLM fallback extraction
# ─────────────────────────────────────────────────────────────────────────────
_SYS_PROMPT = """\
Extract structured data from this resume.
Return ONLY a JSON object. No markdown, no explanation.
Format:
{
  "skills": ["skill1", "skill2"],
  "experience": [{"title": "...", "company": "...", "duration": "...", "description": "..."}],
  "education": [{"degree": "...", "institution": "...", "year": "..."}],
  "projects": [{"name": "...", "description": "...", "tech": ["..."]}],
  "summary": "one paragraph summary of the candidate"
}
Rules:
- Extract ALL skills mentioned anywhere in the resume
- Include every job/role in experience
- Include all education entries
- summary should capture the candidate's profile in 2-3 sentences
- output {} if nothing found
"""


def _llm_extract(text: str) -> dict:
    """
    LLM fallback for messy/scanned/non-standard resumes.

    WHY Ollama (not OpenAI):
      - Local inference = no API cost for extraction
      - OpenAI reserved for embeddings (high-value use)
      - Ollama handles extraction quality well enough

    WHY temperature=0:
      - Deterministic extraction, no creative hallucination
      - Same resume should always produce same fields
    """
    truncated = text[:6000]  # LLM context budget
    logger.info("LLM fallback extraction: %d chars", len(truncated))

    try:
        resp = httpx.post(
            f"{settings.OLLAMA_URL}/api/chat",
            json={
                "model": settings.LLM_MODEL,
                "messages": [
                    {"role": "system", "content": _SYS_PROMPT},
                    {"role": "user", "content": truncated},
                ],
                "stream": False,
                "options": {
                    "temperature": settings.LLM_TEMPERATURE,
                    "num_predict": settings.LLM_NUM_PREDICT,
                },
            },
            timeout=120,
        )
        resp.raise_for_status()
        raw = resp.json()["message"]["content"]
    except Exception as exc:
        logger.error("LLM extraction failed: %s", exc)
        return {}

    # Parse JSON from potentially messy LLM output
    clean = re.sub(r"```(?:json)?|```", "", raw).strip()
    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        # Try to find JSON object in the mess
        m = re.search(r"\{.*\}", clean, re.DOTALL)
        if m:
            try:
                parsed = json.loads(m.group())
            except json.JSONDecodeError:
                logger.warning("LLM output not parseable as JSON")
                return {}
        else:
            return {}

    return parsed if isinstance(parsed, dict) else {}


# ─────────────────────────────────────────────────────────────────────────────
# Merge strategy (same principle as biomarker _merge)
# ─────────────────────────────────────────────────────────────────────────────
def _merge_results(regex_result: dict, llm_result: dict) -> dict:
    """
    Merge regex + LLM results. Regex wins on conflicts.

    WHY regex wins:
      - Deterministic (same input → same output)
      - No hallucination risk
      - LLM fills gaps where regex found nothing

    Same principle as biomarker pipeline: table results > text results > LLM.
    """
    merged = {}

    # Skills: union of both, regex entries first
    regex_skills = set(s.lower() for s in regex_result.get("skills", []))
    llm_skills = llm_result.get("skills", [])
    merged["skills"] = regex_result.get("skills", []) + [
        s for s in llm_skills if s.lower() not in regex_skills
    ]

    # Experience: regex if non-empty, else LLM
    merged["experience"] = (
        regex_result.get("experience")
        or llm_result.get("experience")
        or []
    )

    # Education: regex if non-empty, else LLM
    merged["education"] = (
        regex_result.get("education")
        or llm_result.get("education")
        or []
    )

    # Projects: regex if non-empty, else LLM
    merged["projects"] = (
        regex_result.get("projects")
        or llm_result.get("projects")
        or []
    )

    # Summary: LLM generates better summaries than regex
    merged["summary"] = (
        llm_result.get("summary")
        or regex_result.get("summary", "")
    )

    # Contact: always from regex (LLM shouldn't generate contact info)
    merged["contact"] = regex_result.get("contact", {})

    return merged


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────
def extract_resume(text: str) -> dict:
    """
    Extract structured fields from resume text.

    Strategy:
      1. Split text into sections
      2. Parse each section with regex
      3. If total extraction is thin, run LLM fallback
      4. Merge results (regex wins on conflicts)

    Returns structured dict for downstream chunking + embedding.
    """
    sections = _split_sections(text)

    # Regex-based extraction
    regex_result: dict[str, Any] = {
        "contact": _extract_contact(text),
        "skills": _extract_skills(sections.get("skills", "")),
        "experience": _extract_experience(sections.get("experience", "")),
        "education": _extract_education(sections.get("education", "")),
        "projects": _extract_projects(sections.get("projects", "")),
        "summary": sections.get("summary", ""),
    }

    total_extracted = (
        len(regex_result["skills"])
        + len(regex_result["experience"])
        + len(regex_result["education"])
    )

    logger.info(
        "Regex extraction: skills=%d, exp=%d, edu=%d",
        len(regex_result["skills"]),
        len(regex_result["experience"]),
        len(regex_result["education"]),
    )

    # LLM fallback if regex found very little
    if total_extracted < 5:
        logger.info(
            "Low regex extraction (%d items) — running LLM fallback",
            total_extracted,
        )
        llm_result = _llm_extract(text)
        if llm_result:
            logger.info("LLM added data, merging")
            return _merge_results(regex_result, llm_result)

    return regex_result
