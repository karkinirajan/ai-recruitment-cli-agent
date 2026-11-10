"""Reading text out of CV and job-description files (PDF and DOCX)."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pdfplumber
from docx import Document

SUPPORTED_CV_FORMATS = {".pdf", ".docx"}
MAX_FILE_BYTES = 25 * 1024 * 1024  # a CV or job description larger than this is skipped
MAX_UNPACKED_BYTES = 200 * 1024 * 1024  # a DOCX is a zip file: refuse one that unpacks to more than this (a zip bomb)
MAX_PDF_PAGES = 50  # only the first pages are read


class ExtractionError(Exception):
    """A file cannot be read; the message says why (it is safe to show)."""


def _check_size(path: Path) -> None:
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ExtractionError(f"file is {size / 1024 / 1024:.0f} MB, over the {MAX_FILE_BYTES // 1024 // 1024} MB limit")


def extract_text_from_pdf(path: Path) -> str:
    """All text of the first pages of a PDF. Raises ExtractionError for a file that is too large, unreadable, or has no text (a scan)."""
    _check_size(path)
    try:
        parts: list[str] = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages[:MAX_PDF_PAGES]:
                page_text = page.extract_text()
                if page_text:
                    parts.append(page_text)
    except Exception as exc:  # pdfminer raises many different errors for damaged files
        raise ExtractionError(f"cannot read the PDF ({type(exc).__name__})") from exc
    text = "\n".join(parts).strip()
    if not text:
        raise ExtractionError("no text found (a scanned, image-only or password-protected PDF?)")
    return text


def extract_text_from_docx(path: Path) -> str:
    """All paragraph text of a DOCX. Raises ExtractionError for a file that is too large, unreadable, or empty."""
    _check_size(path)
    try:
        with zipfile.ZipFile(path) as archive:
            if sum(info.file_size for info in archive.infolist()) > MAX_UNPACKED_BYTES:
                raise ExtractionError("the document unpacks to more than the allowed size")
        document = Document(str(path))
        text = "\n".join(p.text for p in document.paragraphs if p.text.strip()).strip()
    except ExtractionError:
        raise
    except Exception as exc:  # a damaged or non-DOCX file
        raise ExtractionError(f"cannot read the DOCX ({type(exc).__name__})") from exc
    if not text:
        raise ExtractionError("no text found")
    return text


def extract_text(path: Path) -> str:
    """The text of a .pdf or .docx file, chosen by its extension."""
    if path.suffix.lower() == ".pdf":
        return extract_text_from_pdf(path)
    return extract_text_from_docx(path)
