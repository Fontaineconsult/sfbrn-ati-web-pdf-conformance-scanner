from __future__ import annotations

import pikepdf

from pdfscan.classify.classifier import Label
from pdfscan.classify.evaluate import (
    classify_file,
    compute_metrics,
    evaluate,
    load_labeled_set,
)
from pdfscan.classify.profile import DEFAULT_PROFILE
from pdfscan.config import IgnoreProfiles, load_settings

EMPTY_IGNORE = IgnoreProfiles(ignore={}, immediate_failures={})


def _blank_pdf(path) -> None:
    pdf = pikepdf.Pdf.new()
    pdf.add_blank_page(page_size=(200, 200))
    pdf.save(path)
    pdf.close()


def _settings(tmp_path):
    return load_settings(config_path=tmp_path / "missing.yaml")


# -- pure metrics --------------------------------------------------------------
def test_compute_metrics_perfect():
    pairs = [
        ("good_to_go", "good_to_go"),
        ("needs_manual_remediation", "needs_manual_remediation"),
    ]
    acc, confusion, per_class = compute_metrics(pairs)
    assert acc == 1.0
    assert confusion["good_to_go"]["good_to_go"] == 1
    assert per_class["good_to_go"]["precision"] == 1.0
    assert per_class["good_to_go"]["recall"] == 1.0


def test_compute_metrics_with_mistakes():
    pairs = [
        ("good_to_go", "good_to_go"),
        ("good_to_go", "needs_manual_remediation"),  # FN for good, FP for manual
        ("needs_manual_remediation", "needs_manual_remediation"),
    ]
    acc, confusion, per_class = compute_metrics(pairs)
    assert abs(acc - 2 / 3) < 1e-9
    assert confusion["good_to_go"]["needs_manual_remediation"] == 1
    # good_to_go: 1 correct of 2 expected -> recall 0.5, precision 1.0 (never wrongly predicted)
    assert per_class["good_to_go"]["recall"] == 0.5
    assert per_class["good_to_go"]["precision"] == 1.0
    # manual: predicted twice, 1 correct -> precision 0.5, recall 1.0
    assert per_class["needs_manual_remediation"]["precision"] == 0.5
    assert per_class["needs_manual_remediation"]["recall"] == 1.0


def test_compute_metrics_counts_error_predictions_against_accuracy():
    acc, confusion, _ = compute_metrics([("good_to_go", "error")])
    assert acc == 0.0
    # "error" is not a matrix column -> the row stays all-zero, no crash
    assert confusion["good_to_go"]["good_to_go"] == 0


# -- label folder parsing ------------------------------------------------------
def test_load_labeled_set_aliases_and_skips_unknown(tmp_path):
    for sub in ("good_to_go", "auto", "manual", "junk"):
        (tmp_path / sub).mkdir()
    (tmp_path / "good_to_go" / "a.pdf").write_bytes(b"%PDF-1.7")
    (tmp_path / "auto" / "b.pdf").write_bytes(b"%PDF-1.7")
    (tmp_path / "manual" / "c.pdf").write_bytes(b"%PDF-1.7")
    (tmp_path / "junk" / "d.pdf").write_bytes(b"%PDF-1.7")  # unknown dir -> skipped

    labeled = load_labeled_set(tmp_path)
    by_name = {p.name: lab for p, lab in labeled}
    assert by_name["a.pdf"] is Label.good_to_go
    assert by_name["b.pdf"] is Label.fit_for_automated_tagging  # alias 'auto'
    assert by_name["c.pdf"] is Label.needs_manual_remediation  # alias 'manual'
    assert "d.pdf" not in by_name


def test_load_labeled_set_missing_dir_is_empty(tmp_path):
    assert load_labeled_set(tmp_path / "nope") == []


# -- classify_file / evaluate (veraPDF mocked, real structural analysis) --------
def test_classify_file_blank_is_good_to_go(tmp_path, monkeypatch):
    import pdfscan.classify.evaluate as ev

    monkeypatch.setattr(ev, "run_verapdf", lambda *a, **k: {})  # no failing rules
    p = tmp_path / "blank.pdf"
    _blank_pdf(p)
    c = classify_file(p, _settings(tmp_path), "verapdf", EMPTY_IGNORE, DEFAULT_PROFILE)
    # tagged-by-default summary + zero violations -> good_to_go
    assert c.label is Label.good_to_go


def test_evaluate_builds_confusion_and_mismatches(tmp_path, monkeypatch):
    import pdfscan.classify.evaluate as ev

    monkeypatch.setattr(ev, "run_verapdf", lambda *a, **k: {})
    good = tmp_path / "good.pdf"
    mis = tmp_path / "mis.pdf"
    _blank_pdf(good)
    _blank_pdf(mis)
    labeled = [(good, Label.good_to_go), (mis, Label.needs_manual_remediation)]

    report = evaluate(labeled, _settings(tmp_path), "verapdf", EMPTY_IGNORE, DEFAULT_PROFILE)
    d = report.to_dict()
    assert d["total"] == 2
    assert d["accuracy"] == 0.5  # both predicted good_to_go; one expected manual
    assert d["confusion"]["needs_manual_remediation"]["good_to_go"] == 1
    assert len(d["mismatches"]) == 1
    miss = d["mismatches"][0]
    assert miss["expected"] == "needs_manual_remediation"
    assert miss["predicted"] == "good_to_go"
    assert "signals" in miss
