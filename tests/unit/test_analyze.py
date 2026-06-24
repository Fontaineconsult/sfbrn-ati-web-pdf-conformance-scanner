from __future__ import annotations

import pikepdf

from pdfscan.pdf.analyze import PdfAnalysis, analyze_pdf

_ALLOWED_TEXT_TYPES = {"Image Only", "Hybrid", "Text", None}


def _make_blank_pdf(path, pages: int = 1) -> None:
    pdf = pikepdf.Pdf.new()
    for _ in range(pages):
        pdf.add_blank_page(page_size=(200, 200))
    pdf.save(path)
    pdf.close()


def _make_meta_pdf(path) -> None:
    pdf = pikepdf.Pdf.new()
    pdf.add_blank_page(page_size=(200, 200))
    with pdf.open_metadata() as meta:
        meta["dc:title"] = "A Meaningful Title"
    pdf.Root.Lang = pikepdf.String("en-US")
    pdf.save(path)
    pdf.close()


def test_page_count_blank_two_pages(tmp_path):
    p = tmp_path / "blank2.pdf"
    _make_blank_pdf(p, pages=2)
    result = analyze_pdf(p)
    assert isinstance(result, PdfAnalysis)
    assert result.page_count == 2


def test_metadata_title_and_language_set(tmp_path):
    p = tmp_path / "meta.pdf"
    _make_meta_pdf(p)
    result = analyze_pdf(p)
    assert result is not None
    assert result.title_set is True
    assert result.language_set is True


def test_metadata_absent(tmp_path):
    p = tmp_path / "plain.pdf"
    _make_blank_pdf(p, pages=1)
    result = analyze_pdf(p)
    assert result is not None
    assert result.title_set is False
    assert result.language_set is False


def test_non_pdf_returns_none(tmp_path):
    p = tmp_path / "not_a.pdf"
    p.write_text("this is plainly not a PDF file", encoding="utf-8")
    assert analyze_pdf(p) is None


def test_text_type_is_one_of_allowed(tmp_path):
    p = tmp_path / "blank.pdf"
    _make_blank_pdf(p, pages=1)
    result = analyze_pdf(p)
    assert result is not None
    # Blank synthetic pages have no text and no image, so the exact value is
    # not deterministic across pdfminer versions -- just assert it is valid.
    assert result.text_type in _ALLOWED_TEXT_TYPES


def test_blank_pdf_is_untagged_and_formless(tmp_path):
    p = tmp_path / "blank.pdf"
    _make_blank_pdf(p, pages=1)
    result = analyze_pdf(p)
    assert result is not None
    assert result.tagged is False
    assert result.has_form is False
