from __future__ import annotations

from pdfscan.classify import classify_rows
from pdfscan.classify.classifier import Confidence, Label, classify_pdf
from pdfscan.classify.profile import DEFAULT_PROFILE, ClassificationProfile
from pdfscan.config import load_ignore_profiles
from pdfscan.db.repositories import (
    PdfRepository,
    ReportRepository,
    SiteRepository,
)
from pdfscan.models import DiscoveredPdf, PdfReport, ReportRule

PROFILE = DEFAULT_PROFILE


def _row(**kw) -> dict:
    """A verified export_rows-style dict; override only the fields a test cares about."""
    base = {
        "pdf_url": "https://x/a.pdf",
        "file_hash": "h",
        "violations": 0,
        "tagged": True,
        "image_only": False,
        "has_form": False,
        "complex_graphic": False,
        "title_set": True,
        "language_set": True,
        "page_count": 3,
    }
    base.update(kw)
    return base


def _rule(clause: str, test: str = "1") -> ReportRule:
    return ReportRule(clause=clause, test_number=test, failed_checks=1)


# -- pending / good_to_go ------------------------------------------------------
def test_pending_when_not_verified():
    c = classify_pdf(_row(violations=None), [], PROFILE)
    assert c.label is Label.pending


def test_good_to_go_tagged_zero_violations():
    c = classify_pdf(_row(violations=0, tagged=True), [], PROFILE)
    assert c.label is Label.good_to_go
    assert c.confidence is Confidence.high
    assert "no counted violations" in c.reason


def test_require_title_drops_good_doc_to_middle_band():
    prof = ClassificationProfile(require_title_for_good=True)
    c = classify_pdf(_row(violations=0, tagged=True, title_set=False), [], prof)
    # no longer good_to_go; tagged+clean scores high -> auto
    assert c.label is Label.fit_for_automated_tagging
    assert "missing title" in c.reason


# -- structural hard routes (win over a clean doc) -----------------------------
def test_image_only_routes_manual_over_clean():
    c = classify_pdf(_row(violations=0, tagged=True, image_only=True), [], PROFILE)
    assert c.label is Label.needs_manual_remediation
    assert c.confidence is Confidence.high
    assert "scanned" in c.reason or "OCR" in c.reason


def test_has_form_routes_manual():
    c = classify_pdf(_row(violations=0, tagged=True, has_form=True), [], PROFILE)
    assert c.label is Label.needs_manual_remediation
    assert "form" in c.reason


def test_complex_graphic_routes_manual_borderline():
    c = classify_pdf(_row(violations=0, tagged=True, complex_graphic=True), [], PROFILE)
    assert c.label is Label.needs_manual_remediation
    assert c.confidence is Confidence.borderline
    assert "complex graphic" in c.reason


def test_structural_override_disabled_when_not_manual():
    prof = ClassificationProfile(structural={})  # nothing hard-routes
    c = classify_pdf(_row(violations=0, tagged=True, image_only=True), [], prof)
    assert c.label is not Label.needs_manual_remediation


# -- manual clause route -------------------------------------------------------
def test_manual_clause_routes_manual():
    c = classify_pdf(_row(violations=2, tagged=True), [_rule("7.3"), _rule("7.1")], PROFILE)
    assert c.label is Label.needs_manual_remediation
    assert "7.3" in c.reason


def test_subclause_inherits_manual_via_prefix():
    c = classify_pdf(_row(violations=1, tagged=True), [_rule("7.18.6.2")], PROFILE)
    assert c.label is Label.needs_manual_remediation
    assert "7.18.6.2" in c.reason


# -- middle band (weighted score) ----------------------------------------------
def test_untagged_clean_is_auto():
    c = classify_pdf(_row(violations=0, tagged=False), [], PROFILE)
    assert c.label is Label.fit_for_automated_tagging
    assert "untagged" in c.reason


def test_score_boundary_just_auto():
    # start 100 - 4*12 = 52 >= auto_threshold 50 -> auto, borderline (|52-50|=2)
    c = classify_pdf(_row(violations=12, tagged=False), [], PROFILE)
    assert c.label is Label.fit_for_automated_tagging
    assert c.confidence is Confidence.borderline


def test_score_boundary_just_manual():
    # 100 - 4*13 = 48 < 50 -> manual, borderline
    c = classify_pdf(_row(violations=13, tagged=False), [], PROFILE)
    assert c.label is Label.needs_manual_remediation
    assert c.confidence is Confidence.borderline
    assert "< 50" in c.reason


def test_neutral_clauses_penalised_into_manual():
    # 8 distinct unmapped clauses: 100 - 4*2 - 8*8 = 28 < 50 -> manual, high
    neutral = [_rule(f"9.{i}") for i in range(8)]
    c = classify_pdf(_row(violations=2, tagged=True), neutral, PROFILE)
    assert c.label is Label.needs_manual_remediation
    assert c.confidence is Confidence.high


# -- apply: ignore policy filters counted rules --------------------------------
def test_classify_rows_excludes_ignored_manual_rule(conn, sample_site, tmp_path):
    sid = SiteRepository(conn).add(sample_site)
    pdfs = PdfRepository(conn)
    pid = pdfs.upsert(DiscoveredPdf("https://x/a.pdf", "https://x/", sid))
    pdfs.set_verified(pid, "h", None)
    ReportRepository(conn).upsert(PdfReport(pdf_hash="h", violations=0, tagged=True))
    # a manual 7.3 rule exists but the ignore policy ignores 7.3/1 -> not counted
    ReportRepository(conn).replace_rules("h", [_rule("7.3", "1")])
    ig = tmp_path / "ig.yaml"
    ig.write_text('ignore:\n  "7.3": ["1"]\n', encoding="utf-8")
    ignore = load_ignore_profiles(ig)

    rows = pdfs.export_rows(sid)
    out = classify_rows(conn, rows, ignore, DEFAULT_PROFILE)
    # 7.3 was ignored, so the doc is clean+tagged -> good_to_go (not manual)
    assert out["https://x/a.pdf"].label is Label.good_to_go
