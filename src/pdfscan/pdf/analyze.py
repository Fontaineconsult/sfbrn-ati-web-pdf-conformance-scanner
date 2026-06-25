"""Structural / content analysis of a PDF using pikepdf and pdfminer.

Ports the relevant pieces of the original ``pdf_priority.py`` (tagging,
form, metadata, language, and page text-vs-image heuristics) into a single
:func:`analyze_pdf` entry point returning a :class:`PdfAnalysis`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pikepdf
from pdfminer import high_level
from pdfminer.layout import LTFigure, LTImage, LTTextContainer

# Cap how many pages we run pdfminer layout analysis over. pdfminer page
# analysis is expensive; sampling the first N pages keeps analysis bounded
# while still being representative for text-vs-image classification.
_MAX_PAGES_FOR_TEXT_ANALYSIS = 25

# A figure (image) is treated as a full-page "image of text" when its area is
# within this fraction band of the page area.
_FULL_PAGE_AREA_LOW = 0.9
_FULL_PAGE_AREA_HIGH = 1.1


@dataclass(frozen=True)
class PdfAnalysis:
    """Result of structurally analysing a single PDF.

    Attributes:
        tagged: Document declares a ``/StructTreeRoot``.
        has_form: Document has AcroForm fields (form-field annotations).
        text_type: ``"Image Only"`` / ``"Hybrid"`` / ``"Text"`` or ``None``
            when no text and no full-page image were detected. This is a
            content heuristic for diagnostics only -- veraPDF's clause 7.1/3
            flag (the report's ``image_only``) is authoritative for the
            image-only determination.
        title_set: A non-empty document title is present (docinfo or XMP).
        language_set: The catalog declares a non-empty ``/Lang``.
        page_count: Number of pages, or ``None`` if it could not be read.
    """

    tagged: bool
    has_form: bool
    text_type: str | None
    title_set: bool
    language_set: bool
    page_count: int | None


def analyze_pdf(pdf_path: str | Path) -> PdfAnalysis | None:
    """Analyze the PDF at ``pdf_path``.

    Returns a :class:`PdfAnalysis`, or ``None`` if the file cannot be opened
    or read as a PDF.
    """
    try:
        pdf = pikepdf.Pdf.open(pdf_path)
    except (pikepdf.PdfError, OSError, ValueError):
        return None

    try:
        page_count = len(pdf.pages)
        tagged = _check_if_tagged(pdf)
        has_form = _check_for_forms(pdf)
        title_set, language_set = _check_metadata(pdf)
    except Exception:  # noqa: BLE001 - defensive: never raise on a bad PDF
        return None
    finally:
        pdf.close()

    # Text-type analysis is a separate (best-effort) pdfminer pass. Failures
    # here should not invalidate the structural results already gathered.
    text_type = _pdf_text_type(pdf_path)

    return PdfAnalysis(
        tagged=tagged,
        has_form=has_form,
        text_type=text_type,
        title_set=title_set,
        language_set=language_set,
        page_count=page_count,
    )


def is_encrypted(pdf_path: str | Path) -> bool:
    """Return True if the PDF is password-protected (needs a password to open).

    Used to give a distinct signal when :func:`analyze_pdf` returns ``None``: an
    encrypted document is a known, explainable case rather than a corrupt file.
    """
    try:
        with pikepdf.Pdf.open(pdf_path):
            return False
    except pikepdf.PasswordError:
        return True
    except Exception:  # noqa: BLE001 - any other open error is "not encrypted, just unreadable"
        return False


def _check_if_tagged(pdf: pikepdf.Pdf) -> bool:
    """Return True if the catalog declares a ``/StructTreeRoot``."""
    return pdf.Root.get("/StructTreeRoot") is not None


def _check_for_forms(pdf: pikepdf.Pdf) -> bool:
    """Return True if any page has a form-field annotation (``/FT``).

    Mirrors the original ``check_for_forms``: walks each page's ``/Annots``
    looking for an annotation carrying a field-type key, which indicates an
    AcroForm widget.
    """
    for page in pdf.pages:
        if "/Annots" not in page:
            continue
        annots = page["/Annots"]
        try:
            for annot in annots:
                if "/FT" in annot:
                    return True
        except (TypeError, AttributeError):
            continue
    return False


def _check_metadata(pdf: pikepdf.Pdf) -> tuple[bool, bool]:
    """Return ``(title_set, language_set)`` for the document.

    ``title_set`` is True when either the XMP ``dc:title`` or the docinfo
    ``/Title`` is present and non-empty. ``language_set`` is True when the
    catalog declares a non-empty ``/Lang``.
    """
    title_set = False
    language_set = False

    lang = pdf.Root.get("/Lang")
    if lang is not None and str(lang).strip():
        language_set = True

    # XMP metadata (preferred).
    try:
        with pdf.open_metadata() as meta:
            title = meta.get("dc:title")
            if title and str(title).strip():
                title_set = True
    except Exception:  # noqa: BLE001 - XMP may be absent/malformed
        pass

    # Fall back to the docinfo dictionary /Title.
    if not title_set:
        try:
            docinfo_title = pdf.docinfo.get("/Title")
            if docinfo_title is not None and str(docinfo_title).strip():
                title_set = True
        except Exception:  # noqa: BLE001 - docinfo may be absent
            pass

    return title_set, language_set


def _page_contains_text(page) -> bool:
    """Return True if the laid-out page contains any text container."""
    for item in page:
        if isinstance(item, LTTextContainer):
            return True
    return False


def _image_over_text(page) -> bool:
    """Return True if the page has a (roughly) full-page image figure.

    Ports the original ``image_over_text`` heuristic: a figure whose area is
    within ~10% of the page area and which contains an image is treated as a
    full-page "image of text".
    """
    page_area = (page.x1 - page.x0) * (page.y1 - page.y0)
    if page_area <= 0:
        return False

    for item in page:
        if not isinstance(item, LTFigure):
            continue
        has_image = any(isinstance(obj, LTImage) for obj in item)
        if not has_image:
            continue
        variance = ((item.x1 - item.x0) * (item.y1 - item.y0)) / page_area
        if _FULL_PAGE_AREA_LOW < variance < _FULL_PAGE_AREA_HIGH:
            return True
    return False


def _pdf_text_type(pdf_path: str | Path) -> str | None:
    """Classify the document's text content (diagnostic heuristic only).

    This complements but does not override veraPDF: the authoritative image-only
    verdict is veraPDF clause 7.1/3 (the report's ``image_only`` flag). This
    pdfminer classification is retained for insight when the two disagree.

    Returns:
        ``"Hybrid"``     - full-page images *and* extractable text present.
        ``"Text"``       - extractable text but no full-page image of text.
        ``"Image Only"`` - full-page image(s) of text but no extractable text.
        ``None``         - neither full-page images nor extractable text
                           (e.g. truly blank pages).

    Only the first ``_MAX_PAGES_FOR_TEXT_ANALYSIS`` pages are inspected for
    performance; this is sufficient to classify a document's dominant type.
    """
    image_pages = 0
    text_pages = 0

    try:
        pages = high_level.extract_pages(str(pdf_path))
        for index, page in enumerate(pages):
            if index >= _MAX_PAGES_FOR_TEXT_ANALYSIS:
                break
            if _image_over_text(page):
                image_pages += 1
            if _page_contains_text(page):
                text_pages += 1
    except Exception:  # noqa: BLE001 - pdfminer can choke on odd PDFs
        return None

    if image_pages > 0 and text_pages > 0:
        return "Hybrid"
    if image_pages == 0 and text_pages > 0:
        return "Text"
    if image_pages > 0 and text_pages == 0:
        return "Image Only"
    return None
