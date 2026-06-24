from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PdfReport:
    """A persisted ``pdf_report`` row (veraPDF + structural analysis result)."""

    pdf_hash: str
    violations: int = 0
    failed_checks: int = 0
    tagged: bool = False
    image_only: bool = False
    text_type: str | None = None
    title_set: bool = False
    language_set: bool = False
    page_count: int | None = None
    has_form: bool = False
    id: int | None = None
    created_at: str | None = None
