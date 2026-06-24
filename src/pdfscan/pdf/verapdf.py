"""Parsing (and invocation) of veraPDF PDF/UA validation output.

The heavy lifting is :func:`parse_verapdf`, which walks the veraPDF JSON
report and produces a :class:`VeraSummary`. The ignore/flag decisions are
driven entirely by an injected :class:`~pdfscan.config.IgnoreProfiles`
instance so the policy lives in config rather than in code.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pdfscan.config import IgnoreProfiles


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


def parse_verapdf(report_json: dict, ignore: IgnoreProfiles) -> VeraSummary:
    """Parse a veraPDF JSON report into a :class:`VeraSummary`.

    Navigates ``report_json["report"]["jobs"][0]["validationResult"]``. The
    ``validationResult`` value may be either a dict (older veraPDF) or a list
    (newer veraPDF); both are handled. When it is missing or empty a clean
    summary (``tagged=True``, ``image_only=False``, ``0/0``) is returned.

    For each rule summary:
      * If ``ignore.is_ignored(clause, test)`` the rule is skipped entirely.
      * Otherwise its flag (if any) is applied: ``"tagged"`` flips ``tagged``
        to ``False`` and ``"image_only"`` flips ``image_only`` to ``True``.
      * The rule is counted: ``violations`` += 1 and ``failed_checks`` +=
        the rule's ``failedChecks`` (default 0).
    """
    tagged = True
    image_only = False
    violations = 0
    failed_checks = 0

    validation_result = _extract_validation_result(report_json)
    if not isinstance(validation_result, dict):
        return VeraSummary(
            violations=0,
            failed_checks=0,
            tagged=True,
            image_only=False,
        )

    details = validation_result.get("details") or {}
    rules = details.get("ruleSummaries") or []

    for rule in rules:
        clause = rule.get("clause")
        test = rule.get("testNumber")

        if ignore.is_ignored(clause, test):
            continue

        flag = ignore.flag_for(clause, test)
        if flag == "tagged":
            tagged = False
        elif flag == "image_only":
            image_only = True

        violations += 1
        failed_checks += rule.get("failedChecks", 0)

    return VeraSummary(
        violations=violations,
        failed_checks=failed_checks,
        tagged=tagged,
        image_only=image_only,
    )


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
