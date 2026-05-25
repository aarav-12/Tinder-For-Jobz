"""
PDF text extraction — first stage of the resume pipeline.

WHY pdfplumber (not PyPDF2, not pdf-parse):
  - Handles multi-column layouts better (common in resumes)
  - Table extraction built-in (for structured resume sections)
  - Preserves spatial positioning (important for column detection)
  - Same library used in biomarker pipeline — proven reliable

WHY this is a separate module:
  - Single Responsibility: extraction ≠ parsing ≠ chunking
  - If we swap PDF libraries later, only this file changes
  - Testable in isolation: give it a PDF, get text back

Edge cases handled:
  ✅ Empty pages (returns "" per page, not None crash)
  ✅ Encrypted PDFs (caught + logged, not silent failure)
  ✅ Multi-page resumes (concatenated with page markers)
  ✅ Binary/scanned PDFs (returns empty string — LLM fallback upstream)
"""

from __future__ import annotations

import logging

import pdfplumber

logger = logging.getLogger(__name__)


def extract_text(pdf_path: str) -> str:
    """
    Extract raw text from all pages of a PDF.

    Returns concatenated text with page boundaries marked.
    Caller decides what to do with empty results.
    """
    pages: list[str] = []

    try:
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                page_text = page.extract_text() or ""
                if page_text.strip():
                    pages.append(page_text)
                else:
                    logger.debug("Page %d: empty or image-only", i + 1)
    except Exception as exc:
        logger.error("PDF extraction failed: %s", exc)
        return ""

    full_text = "\n\n".join(pages)
    logger.info(
        "Extracted %d chars from %d non-empty pages",
        len(full_text),
        len(pages),
    )
    return full_text


def extract_text_by_page(pdf_path: str) -> list[str]:
    """
    Extract text page-by-page. Useful when chunking needs
    page-level granularity (e.g., multi-page resumes where
    page 1 = summary, page 2 = experience).
    """
    pages: list[str] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                pages.append(page.extract_text() or "")
    except Exception as exc:
        logger.error("PDF page extraction failed: %s", exc)
    return pages

