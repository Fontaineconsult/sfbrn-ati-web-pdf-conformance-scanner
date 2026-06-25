"""The three-signal remediation classifier (pure decision logic).

Emits one of three actionable triage signals for a verified PDF:

* ``good_to_go``                 -- accessible; no remediation needed.
* ``fit_for_automated_tagging``  -- an auto-tagger (Adobe Autotag / PDFix) can fix it.
* ``needs_manual_remediation``   -- a human must remediate it.

There is no industry-standard formula for this split, so the engine is a
**hybrid**: a hard-route decision tree for the clear cases (scanned, forms,
complex graphics, manual-only clause failures, and clean tagged docs) plus a
tunable weighted **score** that arbitrates only the fuzzy middle band. Every
threshold lives in a :class:`~pdfscan.classify.profile.ClassificationProfile`,
so behaviour is config-driven and re-evaluated at read time.

:func:`classify_pdf` is a pure function of ``(row, counted_rules, profile)`` --
the ``row`` is one ``export_rows`` dict, ``counted_rules`` are the failing
veraPDF rules that survive the ignore policy -- so it is trivially unit-testable
with plain dicts.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from pdfscan.classify.profile import ClassificationProfile
from pdfscan.models import ReportRule


class Label(StrEnum):
    pending = "pending"
    good_to_go = "good_to_go"
    fit_for_automated_tagging = "fit_for_automated_tagging"
    needs_manual_remediation = "needs_manual_remediation"


class Confidence(StrEnum):
    high = "high"
    borderline = "borderline"  # near a cutoff / driven by a heuristic signal


@dataclass(frozen=True)
class Classification:
    label: Label
    reason: str
    confidence: Confidence = Confidence.high


def _distinct_clauses(rules: Iterable[ReportRule]) -> list[str]:
    """Distinct, non-null clauses among the counted rules (first-seen order)."""
    seen: set[str] = set()
    out: list[str] = []
    for rule in rules:
        clause = rule.clause
        if clause is None or clause in seen:
            continue
        seen.add(clause)
        out.append(clause)
    return out


def _auto_reason(*, tagged: bool, violations: int, title: bool, language: bool) -> str:
    """Human-readable 'why auto-fixable' for the ``fit_for_automated_tagging`` band."""
    bits: list[str] = []
    if not tagged:
        bits.append("untagged (auto-tag adds structure)")
    if violations:
        bits.append(f"{violations} fixable violation(s)")
    if not language:
        bits.append("missing /Lang")
    if not title:
        bits.append("missing title")
    return "; ".join(bits) if bits else "auto-remediable"


def classify_pdf(
    row: dict,
    rules: Iterable[ReportRule],
    profile: ClassificationProfile,
) -> Classification:
    """Classify one verified-PDF ``row`` into a remediation triage signal.

    ``rules`` must already be filtered to the *counted* failing rules (ignore
    policy applied); ``classify_pdf`` does not consult the ignore profile.
    Ordering is deliberate -- a low violation count must never override a
    scanned/forms/complex-figure document, and clean docs short-circuit before
    the score ever runs:

    1. pending (not yet verified)
    2. structural manual routes (image-only, has-form, complex-graphic)
    3. manual-only clause failure (e.g. complex tables, 7.3)
    4. good_to_go (tagged, zero counted violations, optional metadata strictness)
    5. weighted score -> fit_for_automated_tagging vs needs_manual_remediation
    """
    if row.get("violations") is None:
        return Classification(Label.pending, "not yet verified")

    violations = int(row.get("violations") or 0)
    tagged = bool(row.get("tagged"))
    image_only = bool(row.get("image_only"))
    has_form = bool(row.get("has_form"))
    complex_graphic = bool(row.get("complex_graphic"))
    title = bool(row.get("title_set"))
    language = bool(row.get("language_set"))
    page_count = int(row.get("page_count") or 0)

    # 2. structural manual routes (hard) -- each beats clause routing and score.
    if image_only and profile.structural_override("image_only") == "manual":
        return Classification(
            Label.needs_manual_remediation, "image-only / scanned PDF needs OCR"
        )
    if has_form and profile.structural_override("has_form") == "manual":
        return Classification(
            Label.needs_manual_remediation, "interactive form needs manual field labels"
        )
    if complex_graphic and profile.structural_override("complex_graphic") == "manual":
        return Classification(
            Label.needs_manual_remediation,
            "overlapping image+text suggests a complex graphic",
            Confidence.borderline,
        )

    clauses = _distinct_clauses(rules)

    # 3. manual-only clause failure.
    manual = sorted(c for c in clauses if profile.class_for_clause(c) == "manual")
    if manual:
        return Classification(
            Label.needs_manual_remediation, f"manual-only clause(s): {', '.join(manual)}"
        )

    # 4. good to go: tagged + zero counted violations (+ optional metadata).
    if tagged and violations == 0:
        meets_meta = (not profile.require_title_for_good or title) and (
            not profile.require_language_for_good or language
        )
        if meets_meta:
            return Classification(Label.good_to_go, "tagged, no counted violations")

    # 5. middle band: weighted score decides auto vs manual.
    neutral = sum(1 for c in clauses if profile.class_for_clause(c) is None)
    s = profile.score
    score = (
        s["start"]
        - s["per_violation"] * violations
        - s["per_neutral_clause"] * neutral
        - s["per_page_over"] * max(0, page_count - s["big_doc_pages"])
    )
    threshold = s["auto_threshold"]
    confidence = (
        Confidence.borderline
        if abs(score - threshold) <= s["borderline_band"]
        else Confidence.high
    )
    if score >= threshold:
        return Classification(
            Label.fit_for_automated_tagging,
            _auto_reason(tagged=tagged, violations=violations, title=title, language=language),
            confidence,
        )
    return Classification(
        Label.needs_manual_remediation,
        f"score {int(score)} < {int(threshold)} (too many or unknown violations)",
        confidence,
    )
