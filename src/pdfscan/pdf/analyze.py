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

# "Complex graphic" heuristic: an image whose area is a substantial-but-not-
# full-page fraction of the page (excludes tiny icons and the full-page
# image-of-text already covered by image_only) that a text block sits on top of
# / inside -- e.g. a chart or infographic with embedded labels. Such figures
# need meaningful alt text and resist automated tagging. Tunable.
_COMPLEX_GRAPHIC_MIN_IMAGE_FRAC = 0.05
_COMPLEX_GRAPHIC_MAX_IMAGE_FRAC = 0.9
_COMPLEX_GRAPHIC_TEXT_OVERLAP_FRAC = 0.5


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
        complex_graphic: A substantial image overlaps a text block on some
            sampled page (a chart/infographic with embedded labels). A heuristic
            "needs manual remediation" hint; may false-positive on watermarks or
            banner text.
    """

    tagged: bool
    has_form: bool
    text_type: str | None
    title_set: bool
    language_set: bool
    page_count: int | None
    complex_graphic: bool = False


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

    # Text-type + complex-graphic analysis is a separate (best-effort) pdfminer
    # pass. Failures here should not invalidate the structural results above.
    text_type, complex_graphic = _analyze_pages(pdf_path)

    return PdfAnalysis(
        tagged=tagged,
        has_form=has_form,
        text_type=text_type,
        title_set=title_set,
        language_set=language_set,
        page_count=page_count,
        complex_graphic=complex_graphic,
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


def _overlap_fraction(
    text_bbox: tuple[float, float, float, float],
    image_bbox: tuple[float, float, float, float],
) -> float:
    """Fraction of the text box's area that lies inside the image box (0..1)."""
    tx0, ty0, tx1, ty1 = text_bbox
    ix0, iy0, ix1, iy1 = image_bbox
    w = max(0.0, min(tx1, ix1) - max(tx0, ix0))
    h = max(0.0, min(ty1, iy1) - max(ty0, iy0))
    text_area = (tx1 - tx0) * (ty1 - ty0)
    return (w * h) / text_area if text_area > 0 else 0.0


def _page_has_overlapping_image_text(page) -> bool:
    """True if a substantial image figure on the page is overlapped by text.

    Collects images that occupy a substantial-but-not-full-page fraction of the
    page, then returns True if any text container sits substantially on top of
    one (``>= _COMPLEX_GRAPHIC_TEXT_OVERLAP_FRAC`` of the text box's area) --
    the signature of a chart/infographic with embedded labels.
    """
    page_area = (page.x1 - page.x0) * (page.y1 - page.y0)
    if page_area <= 0:
        return False

    image_boxes: list[tuple[float, float, float, float]] = []
    text_boxes: list[tuple[float, float, float, float]] = []
    for item in page:
        if isinstance(item, LTFigure | LTImage):
            has_image = isinstance(item, LTImage) or any(isinstance(o, LTImage) for o in item)
            if not has_image:
                continue
            frac = ((item.x1 - item.x0) * (item.y1 - item.y0)) / page_area
            if _COMPLEX_GRAPHIC_MIN_IMAGE_FRAC < frac < _COMPLEX_GRAPHIC_MAX_IMAGE_FRAC:
                image_boxes.append((item.x0, item.y0, item.x1, item.y1))
        elif isinstance(item, LTTextContainer):
            text_boxes.append((item.x0, item.y0, item.x1, item.y1))

    return any(
        _overlap_fraction(t, im) >= _COMPLEX_GRAPHIC_TEXT_OVERLAP_FRAC
        for im in image_boxes
        for t in text_boxes
    )


def _analyze_pages(pdf_path: str | Path) -> tuple[str | None, bool]:
    """Single pdfminer pass returning ``(text_type, complex_graphic)``.

    ``text_type`` is a diagnostic content heuristic (NOT authoritative -- veraPDF
    clause 7.1/3 ``image_only`` is): ``"Hybrid"`` (full-page images + text),
    ``"Text"``, ``"Image Only"``, or ``None`` (blank). ``complex_graphic`` is
    True if any sampled page has a substantial image overlapped by text.

    Only the first ``_MAX_PAGES_FOR_TEXT_ANALYSIS`` pages are inspected.
    """
    image_pages = 0
    text_pages = 0
    complex_graphic = False

    try:
        pages = high_level.extract_pages(str(pdf_path))
        for index, page in enumerate(pages):
            if index >= _MAX_PAGES_FOR_TEXT_ANALYSIS:
                break
            if _image_over_text(page):
                image_pages += 1
            if _page_contains_text(page):
                text_pages += 1
            if not complex_graphic and _page_has_overlapping_image_text(page):
                complex_graphic = True
    except Exception:  # noqa: BLE001 - pdfminer can choke on odd PDFs
        return None, False

    if image_pages > 0 and text_pages > 0:
        text_type = "Hybrid"
    elif image_pages == 0 and text_pages > 0:
        text_type = "Text"
    elif image_pages > 0 and text_pages == 0:
        text_type = "Image Only"
    else:
        text_type = None
    return text_type, complex_graphic
