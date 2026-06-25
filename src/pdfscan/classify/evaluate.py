"""Calibration harness: score the classifier against pre-sorted ground-truth.

Drop labelled PDFs into category subfolders::

    eval-set/
      good_to_go/*.pdf
      fit_for_automated_tagging/*.pdf      (aliases: auto, fit)
      needs_manual_remediation/*.pdf       (aliases: manual)

then ``pdfscan eval ./eval-set`` runs each PDF through veraPDF + structural
analysis + the classifier (no crawl, no download, no DB) and reports overall
accuracy, a confusion matrix, per-class precision/recall, and a mismatch list
with the raw signals + classifier reason behind every miss. The JSON report is
the feedback artifact: read the mismatches, turn a knob in
``config/classification.yaml`` (threshold / clause class / score weight /
structural override), and re-run -- because classification is read-time, most
iterations only re-tune the YAML.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pdfscan.classify.classifier import Classification, Label, classify_pdf
from pdfscan.classify.profile import ClassificationProfile
from pdfscan.config import IgnoreProfiles, Settings
from pdfscan.models import ReportRule
from pdfscan.pdf.analyze import analyze_pdf
from pdfscan.pdf.verapdf import extract_rules, run_verapdf, summarize

# The three labels the harness scores over (pending/error are reported but not
# part of the ground-truth label set).
EVAL_LABELS: tuple[str, ...] = (
    Label.good_to_go.value,
    Label.fit_for_automated_tagging.value,
    Label.needs_manual_remediation.value,
)

# Subfolder name (lowercased) -> expected label. Short aliases accepted.
LABEL_ALIASES: dict[str, Label] = {
    "good_to_go": Label.good_to_go,
    "good": Label.good_to_go,
    "go": Label.good_to_go,
    "fit_for_automated_tagging": Label.fit_for_automated_tagging,
    "fit": Label.fit_for_automated_tagging,
    "auto": Label.fit_for_automated_tagging,
    "needs_manual_remediation": Label.needs_manual_remediation,
    "manual": Label.needs_manual_remediation,
}

_SIGNAL_FIELDS = (
    "violations",
    "tagged",
    "image_only",
    "has_form",
    "complex_graphic",
    "page_count",
)


def load_labeled_set(root: str | os.PathLike) -> list[tuple[Path, Label]]:
    """Discover ``(pdf_path, expected_label)`` pairs under category subfolders.

    Each immediate subdirectory whose name is a known label (or alias) contributes
    its ``*.pdf`` files; unrecognised directories are skipped. Returns pairs sorted
    by (label, path) for stable reporting.
    """
    base = Path(root)
    out: list[tuple[Path, Label]] = []
    if not base.is_dir():
        return out
    for sub in sorted(base.iterdir()):
        if not sub.is_dir():
            continue
        label = LABEL_ALIASES.get(sub.name.lower())
        if label is None:
            continue
        for pdf in sorted(sub.glob("*.pdf")):
            out.append((pdf, label))
    return out


def _row_for_file(
    pdf_path: str | os.PathLike,
    verapdf_cmd: str,
    settings: Settings,
    ignore: IgnoreProfiles,
) -> tuple[dict, list[ReportRule]]:
    """Build the ``classify_pdf`` row + counted rules for a loose local PDF."""
    report_json = run_verapdf(
        pdf_path,
        verapdf_cmd,
        flavour=str(settings.get("verapdf.flavour", "ua1")),
        timeout=int(settings.get("verapdf.timeout", 180)),
    )
    rules = extract_rules(report_json)
    vera = summarize(rules, ignore)
    analysis = analyze_pdf(pdf_path)
    row = {
        "pdf_url": str(pdf_path),
        "file_hash": None,
        "violations": vera.violations,
        "tagged": vera.tagged,
        "image_only": vera.image_only,
        "title_set": analysis.title_set if analysis else False,
        "language_set": analysis.language_set if analysis else False,
        "page_count": analysis.page_count if analysis else None,
        "has_form": analysis.has_form if analysis else False,
        "complex_graphic": analysis.complex_graphic if analysis else False,
    }
    counted = [r for r in rules if not ignore.is_ignored(r.clause, r.test_number)]
    return row, counted


def classify_file(
    pdf_path: str | os.PathLike,
    settings: Settings,
    verapdf_cmd: str,
    ignore: IgnoreProfiles,
    profile: ClassificationProfile,
) -> Classification:
    """Classify a single local PDF end-to-end (veraPDF + analysis + classifier).

    A standalone "classify one PDF" primitive -- no crawl, download, or DB.
    """
    row, counted = _row_for_file(pdf_path, verapdf_cmd, settings, ignore)
    return classify_pdf(row, counted, profile)


@dataclass
class EvalItem:
    path: str
    expected: str
    predicted: str
    confidence: str
    reason: str
    correct: bool
    signals: dict = field(default_factory=dict)


@dataclass
class EvalReport:
    total: int
    accuracy: float
    confusion: dict[str, dict[str, int]]
    per_class: dict[str, dict[str, float]]
    items: list[EvalItem]

    @property
    def mismatches(self) -> list[EvalItem]:
        return [it for it in self.items if not it.correct]

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "accuracy": self.accuracy,
            "confusion": self.confusion,
            "per_class": self.per_class,
            "mismatches": [asdict(it) for it in self.mismatches],
            "items": [asdict(it) for it in self.items],
        }


def compute_metrics(
    pairs: list[tuple[str, str]],
    labels: tuple[str, ...] = EVAL_LABELS,
) -> tuple[float, dict[str, dict[str, int]], dict[str, dict[str, float]]]:
    """Pure metrics from ``(expected, predicted)`` pairs.

    Returns ``(accuracy, confusion, per_class)``. The confusion matrix is keyed
    ``expected -> predicted -> count`` over ``labels``; predictions outside
    ``labels`` (e.g. "error") still count against accuracy and recall but are not
    given a matrix column. ``per_class`` carries precision/recall/support.
    """
    confusion = {e: dict.fromkeys(labels, 0) for e in labels}
    for expected, predicted in pairs:
        if expected in confusion and predicted in confusion[expected]:
            confusion[expected][predicted] += 1

    total = len(pairs)
    correct = sum(1 for e, p in pairs if e == p)
    accuracy = correct / total if total else 0.0

    per_class: dict[str, dict[str, float]] = {}
    for lab in labels:
        support = sum(1 for e, _ in pairs if e == lab)
        tp = sum(1 for e, p in pairs if e == lab and p == lab)
        predicted_lab = sum(1 for _, p in pairs if p == lab)  # tp + fp
        precision = tp / predicted_lab if predicted_lab else 0.0
        recall = tp / support if support else 0.0
        per_class[lab] = {
            "precision": precision,
            "recall": recall,
            "support": support,
        }
    return accuracy, confusion, per_class


def evaluate(
    labeled: list[tuple[Path, Label]],
    settings: Settings,
    verapdf_cmd: str,
    ignore: IgnoreProfiles,
    profile: ClassificationProfile,
) -> EvalReport:
    """Classify every labelled PDF and score predictions against expectations."""
    items: list[EvalItem] = []
    pairs: list[tuple[str, str]] = []
    for path, expected in labeled:
        try:
            row, counted = _row_for_file(path, verapdf_cmd, settings, ignore)
            c = classify_pdf(row, counted, profile)
            predicted = c.label.value
            confidence = c.confidence.value
            reason = c.reason
            signals = {k: row.get(k) for k in _SIGNAL_FIELDS}
            signals["clauses"] = sorted({r.clause for r in counted if r.clause})
        except Exception as exc:  # a corrupt/encrypted PDF should not abort the run
            predicted = "error"
            confidence = "high"
            reason = f"classification failed: {exc}"
            signals = {"error": str(exc)}
        exp = expected.value
        items.append(
            EvalItem(
                path=str(path),
                expected=exp,
                predicted=predicted,
                confidence=confidence,
                reason=reason,
                correct=(exp == predicted),
                signals=signals,
            )
        )
        pairs.append((exp, predicted))

    accuracy, confusion, per_class = compute_metrics(pairs)
    return EvalReport(
        total=len(items),
        accuracy=accuracy,
        confusion=confusion,
        per_class=per_class,
        items=items,
    )
