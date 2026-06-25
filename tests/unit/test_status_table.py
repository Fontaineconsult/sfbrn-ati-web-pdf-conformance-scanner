from __future__ import annotations

from pdfscan.cli.status import (
    StatusFilter,
    StatusSort,
    _apply_filter,
    _deschemed,
    _has_issue,
    _is_verified,
    _sort_rows,
    _text_type_cell,
)


def _row(url: str, **over) -> dict:
    base = {
        "site": "s",
        "pdf_url": url,
        "parent_url": "https://x/p",
        "scanned_at": "now",
        "offsite": 0,
        "via_resolver": None,
        "local_path": None,
        "archived": 0,
        "removed": 0,
        "pdf_404": 0,
        "parent_404": 0,
        "file_hash": None,
        "violations": None,
        "failed_checks": None,
        "tagged": None,
        "image_only": None,
        "text_type": None,
        "title_set": None,
        "language_set": None,
        "page_count": None,
        "has_form": None,
    }
    base.update(over)
    return base


def _verified(url: str, **over) -> dict:
    defaults = {"violations": 0, "failed_checks": 0, "tagged": 1, "image_only": 0, "file_hash": "h"}
    defaults.update(over)
    return _row(url, **defaults)


# --- verified / issue predicates ---------------------------------------------
def test_is_verified():
    assert _is_verified(_row("https://x/a.pdf")) is False
    assert _is_verified(_verified("https://x/a.pdf")) is True


def test_has_issue():
    assert _has_issue(_row("https://x/a.pdf")) is False  # pending
    assert _has_issue(_verified("https://x/a.pdf")) is False  # clean + tagged
    assert _has_issue(_verified("https://x/a.pdf", violations=3)) is True
    assert _has_issue(_verified("https://x/a.pdf", tagged=0)) is True
    assert _has_issue(_verified("https://x/a.pdf", image_only=1)) is True


# --- filters ------------------------------------------------------------------
def test_filters_select_expected_rows():
    rows = [
        _row("https://x/pending.pdf"),
        _verified("https://x/clean.pdf"),
        _verified("https://x/bad.pdf", violations=5),
        _row("https://x/off.pdf", offsite=1),
        _row("https://x/arch.pdf", archived=1),
        _row("https://x/broken.pdf", pdf_404=1),
        _row("https://x/pbroken.pdf", parent_404=1),
    ]

    def urls(key):
        return {r["pdf_url"] for r in _apply_filter(rows, key)}

    assert urls(StatusFilter.all) == {r["pdf_url"] for r in rows}
    assert urls(StatusFilter.verified) == {"https://x/clean.pdf", "https://x/bad.pdf"}
    assert "https://x/pending.pdf" in urls(StatusFilter.pending)
    assert urls(StatusFilter.issues) == {"https://x/bad.pdf"}
    assert urls(StatusFilter.offsite) == {"https://x/off.pdf"}
    assert urls(StatusFilter.archived) == {"https://x/arch.pdf"}
    assert urls(StatusFilter.broken) == {"https://x/broken.pdf", "https://x/pbroken.pdf"}


# --- sorting ------------------------------------------------------------------
def test_sort_by_violations_puts_worst_first_and_pending_last():
    rows = [
        _row("https://x/pending.pdf"),
        _verified("https://x/clean.pdf", violations=0),
        _verified("https://x/bad.pdf", violations=9),
        _verified("https://x/mild.pdf", violations=2),
    ]
    ordered = [r["pdf_url"] for r in _sort_rows(rows, StatusSort.violations)]
    assert ordered == [
        "https://x/bad.pdf",
        "https://x/mild.pdf",
        "https://x/clean.pdf",
        "https://x/pending.pdf",
    ]


def test_sort_by_url_is_lexicographic():
    rows = [_row("https://x/b.pdf"), _row("https://x/a.pdf")]
    assert [r["pdf_url"] for r in _sort_rows(rows, StatusSort.url)] == [
        "https://x/a.pdf",
        "https://x/b.pdf",
    ]


# --- display helper -----------------------------------------------------------
def test_deschemed_drops_scheme_keeps_host_path_query():
    assert _deschemed("https://h.edu/docs/a.pdf?x=1") == "h.edu/docs/a.pdf?x=1"
    assert _deschemed("http://h.edu/a.pdf") == "h.edu/a.pdf"


# --- image-only reconciliation (veraPDF authoritative) ------------------------
def test_text_type_cell_passes_through_non_conflicting_types():
    assert _text_type_cell("Text", False) == "Text"
    assert _text_type_cell("Hybrid", False) == "Hybrid"
    # pdfminer and veraPDF agree it's image-only -> shown plainly.
    assert _text_type_cell("Image Only", True) == "Image Only"


def test_text_type_cell_marks_diagnostic_disagreement():
    # pdfminer says image-only but veraPDF (authoritative) did not flag it.
    cell = _text_type_cell("Image Only", False)
    assert "Image Only" in cell and "?" in cell


def test_text_type_cell_none_is_dash():
    assert _text_type_cell(None, False) == "[dim]-[/]"
