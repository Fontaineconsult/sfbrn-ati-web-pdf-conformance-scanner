from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PdfReport:
    """A persisted ``pdf_report`` row (veraPDF + structural analysis result).

    Image-only policy: ``image_only`` (from veraPDF clause 7.1/3) is the
    authoritative image-only verdict. ``text_type`` is a pdfminer content
    heuristic kept for diagnostics only and must not be treated as a second
    image-only signal.
    """

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


@dataclass(frozen=True)
class ReportRule:
    """A single veraPDF rule result (one failing clause/test) for a PDF.

    Stored verbatim from the veraPDF report with **no** ignore policy applied,
    so the ignore profile can be re-evaluated later (e.g. after editing
    ``ignore_profiles.yaml``) without re-downloading and re-running veraPDF. The
    owning ``pdf_hash`` is supplied at persistence time, not held on the rule.
    """

    clause: str | None
    test_number: str | None
    status: str | None = None
    failed_checks: int = 0
    specification: str | None = None
    description: str | None = None
