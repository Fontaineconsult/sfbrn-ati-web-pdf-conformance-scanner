from __future__ import annotations

from pdfscan.config import load_ignore_profiles
from pdfscan.pdf.verapdf import VeraSummary, parse_verapdf

IGNORE = load_ignore_profiles("config/ignore_profiles.yaml")


def _report(validation_result):
    """Wrap a validationResult value in the full veraPDF report envelope."""
    return {"report": {"jobs": [{"validationResult": validation_result}]}}


def _rule_summaries():
    return [
        # (a) in the ignore map (7.2 / 10) -> skipped entirely.
        {"clause": "7.2", "testNumber": "10", "failedChecks": 99},
        # (b) a normal failing rule -> counted (failedChecks 4).
        {"clause": "7.2", "testNumber": "999", "failedChecks": 4},
        # (c) not-tagged rule (7.1 / 11) -> tagged False, counted (1).
        {"clause": "7.1", "testNumber": "11", "failedChecks": 1},
        # (d) image-only rule (7.1 / 3) -> image_only True, counted (1).
        {"clause": "7.1", "testNumber": "3", "failedChecks": 1},
    ]


def test_parse_counts_flags_and_ignores():
    validation_result = {"details": {"ruleSummaries": _rule_summaries()}}
    summary = parse_verapdf(_report(validation_result), IGNORE)

    # The ignored rule (a) is skipped; (b), (c), (d) are counted.
    assert summary.violations == 3
    # failed_checks sum over the counted rules: 4 + 1 + 1.
    assert summary.failed_checks == 6
    assert summary.tagged is False
    assert summary.image_only is True


def test_parse_validation_result_as_list():
    # Newer veraPDF returns validationResult as a list; we take element [0].
    validation_result = [{"details": {"ruleSummaries": _rule_summaries()}}]
    summary = parse_verapdf(_report(validation_result), IGNORE)

    assert summary.violations == 3
    assert summary.failed_checks == 6
    assert summary.tagged is False
    assert summary.image_only is True


def test_parse_empty_list_returns_clean_summary():
    summary = parse_verapdf(_report([]), IGNORE)
    assert summary == VeraSummary(
        violations=0, failed_checks=0, tagged=True, image_only=False
    )


def test_parse_missing_validation_result_returns_clean_summary():
    # Missing validationResult key entirely.
    report = {"report": {"jobs": [{}]}}
    summary = parse_verapdf(report, IGNORE)
    assert summary == VeraSummary(
        violations=0, failed_checks=0, tagged=True, image_only=False
    )


def test_parse_no_jobs_returns_clean_summary():
    report = {"report": {"jobs": []}}
    summary = parse_verapdf(report, IGNORE)
    assert summary == VeraSummary(
        violations=0, failed_checks=0, tagged=True, image_only=False
    )


def test_parse_no_rules_returns_clean_summary():
    validation_result = {"details": {"ruleSummaries": []}}
    summary = parse_verapdf(_report(validation_result), IGNORE)
    assert summary == VeraSummary(
        violations=0, failed_checks=0, tagged=True, image_only=False
    )
