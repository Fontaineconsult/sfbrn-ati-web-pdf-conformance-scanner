"""Parsing (and invocation) of veraPDF PDF/UA validation output.

The heavy lifting is :func:`parse_verapdf`, which walks the veraPDF JSON
report and produces a :class:`VeraSummary`. The ignore/flag decisions are
driven entirely by an injected :class:`~pdfscan.config.IgnoreProfiles`
instance so the policy lives in config rather than in code.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pdfscan.config import IgnoreProfiles
from pdfscan.models import ReportRule


@dataclass(frozen=True)
class VeraSummary:
    """Aggregated result of parsing a single veraPDF report.

    Attributes:
        violations: Number of distinct (non-ignored) failing rules.
        failed_checks: Sum of ``failedChecks`` across the counted rules.
        tagged: ``True`` unless the "not tagged" rule (7.1 / 11) fired.
        image_only: ``True`` if the likely-image-only rule (7.1 / 3) fired.
    """

    violations: int
    failed_checks: int
    tagged: bool
    image_only: bool


def extract_rules(report_json: dict) -> list[ReportRule]:
    """Return every rule summary from a veraPDF report, verbatim (no policy).

    Navigates ``report_json["report"]["jobs"][0]["validationResult"]`` (a dict
    in older veraPDF, a list in newer; both handled) down to
    ``details.ruleSummaries`` and maps each entry to a :class:`ReportRule`.
    Clause/test are normalized to strings (veraPDF may emit ``testNumber`` as an
    int) so they round-trip through the database and the ignore profile cleanly.
    Returns ``[]`` when no validation result / rules are present.
    """
    validation_result = _extract_validation_result(report_json)
    if not isinstance(validation_result, dict):
        return []

    details = validation_result.get("details") or {}
    rules = details.get("ruleSummaries") or []

    out: list[ReportRule] = []
    for rule in rules:
        clause = rule.get("clause")
        test = rule.get("testNumber")
        out.append(
            ReportRule(
                clause=str(clause) if clause is not None else None,
                test_number=str(test) if test is not None else None,
                status=rule.get("ruleStatus") or rule.get("status"),
                failed_checks=int(rule.get("failedChecks") or 0),
                specification=rule.get("specification"),
                description=rule.get("description"),
            )
        )
    return out


def summarize(rules: list[ReportRule], ignore: IgnoreProfiles) -> VeraSummary:
    """Aggregate rule records into a :class:`VeraSummary` under an ignore policy.

    For each rule:
      * If ``ignore.is_ignored(clause, test)`` it is skipped entirely.
      * Otherwise its flag (if any) is applied: ``"tagged"`` flips ``tagged`` to
        ``False`` and ``"image_only"`` flips ``image_only`` to ``True``.
      * The rule is counted: ``violations`` += 1 and ``failed_checks`` += the
        rule's ``failed_checks``.

    Because this operates on stored :class:`ReportRule` records, the policy can
    be re-evaluated later without re-running veraPDF.
    """
    tagged = True
    image_only = False
    violations = 0
    failed_checks = 0

    for rule in rules:
        if ignore.is_ignored(rule.clause, rule.test_number):
            continue

        flag = ignore.flag_for(rule.clause, rule.test_number)
        if flag == "tagged":
            tagged = False
        elif flag == "image_only":
            image_only = True

        violations += 1
        failed_checks += rule.failed_checks

    return VeraSummary(
        violations=violations,
        failed_checks=failed_checks,
        tagged=tagged,
        image_only=image_only,
    )


def parse_verapdf(report_json: dict, ignore: IgnoreProfiles) -> VeraSummary:
    """Parse a veraPDF JSON report into a :class:`VeraSummary`.

    Thin convenience over :func:`extract_rules` + :func:`summarize`, preserved
    for callers/tests that only need the aggregate summary.
    """
    return summarize(extract_rules(report_json), ignore)


def rules_from_job(job: dict) -> list[ReportRule]:
    """Extract rules from a single veraPDF ``jobs[]`` entry (batch output).

    Wraps the job back into the report envelope :func:`extract_rules` expects so
    a batch result and a single-file result share one parsing path.
    """
    return extract_rules({"report": {"jobs": [job]}})


def run_verapdf_batch(
    pdf_paths: list[str | Path],
    verapdf_cmd: str,
    flavour: str = "ua1",
    timeout: int = 1800,
) -> dict[str, dict]:
    """Validate many PDFs in a single veraPDF (JVM) invocation.

    Returns a mapping of ``basename -> job dict`` (one entry per validated file).
    Keying by basename is safe because the caller assigns unique temp filenames
    within a batch; it tolerates veraPDF echoing an absolute or relative path in
    ``itemDetails.name``. Raises :class:`RuntimeError` if veraPDF does not emit
    valid JSON (the caller falls back to per-file validation).

    Amortizes veraPDF's ~1-2s JVM cold start across the whole batch -- the
    dominant cost when verifying hundreds of PDFs.
    """
    paths = [str(p) for p in pdf_paths]
    if not paths:
        return {}
    proc = subprocess.run(
        [verapdf_cmd, "-f", flavour, "--format", "json", *paths],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    try:
        report = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError) as exc:
        stderr_snippet = (proc.stderr or "")[:500]
        raise RuntimeError(
            "veraPDF batch did not produce valid JSON output "
            f"(exit code {proc.returncode}). stderr: {stderr_snippet!r}"
        ) from exc

    jobs = ((report.get("report") or {}).get("jobs")) or []
    out: dict[str, dict] = {}
    for job in jobs:
        if not isinstance(job, dict):
            continue
        name = (job.get("itemDetails") or {}).get("name") or ""
        key = os.path.basename(name)
        if key:
            out[key] = job
    return out


def _extract_validation_result(report_json: dict) -> dict | None:
    """Return the (first) validationResult dict, or ``None`` if absent.

    Tolerates missing intermediate keys, an empty ``jobs`` list, and a
    ``validationResult`` that is either a list (take ``[0]``) or a dict.
    """
    try:
        jobs = report_json["report"]["jobs"]
    except (KeyError, TypeError):
        return None

    if not jobs:
        return None

    job = jobs[0]
    if not isinstance(job, dict):
        return None

    validation_result = job.get("validationResult")
    if isinstance(validation_result, list):
        if not validation_result:
            return None
        validation_result = validation_result[0]

    if isinstance(validation_result, dict):
        return validation_result
    return None


def run_verapdf(
    pdf_path: str | Path,
    verapdf_cmd: str,
    flavour: str = "ua1",
    timeout: int = 180,
) -> dict[str, Any]:
    """Invoke the veraPDF CLI and return its parsed JSON report.

    Builds the argument list explicitly (never ``shell=True``) and parses
    ``stdout`` as JSON. Raises :class:`RuntimeError` with a snippet of
    ``stderr`` if the output is not valid JSON.

    This function is not unit-tested (no binary is available in CI) but is
    importable and ready for integration use.
    """
    proc = subprocess.run(
        [verapdf_cmd, "-f", flavour, "--format", "json", str(pdf_path)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    try:
        return json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError) as exc:
        stderr_snippet = (proc.stderr or "")[:500]
        raise RuntimeError(
            "veraPDF did not produce valid JSON output "
            f"(exit code {proc.returncode}). stderr: {stderr_snippet!r}"
        ) from exc
