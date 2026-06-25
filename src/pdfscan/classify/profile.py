"""Classification policy: a tunable profile mirroring ``config/ignore_profiles.py``.

The profile decides how the three-signal remediation classifier
(``good_to_go`` / ``fit_for_automated_tagging`` / ``needs_manual_remediation``)
routes a PDF. Like the ignore policy it is data, not code: editing
``config/classification.yaml`` re-classifies at read time with no re-verify.

Robustness: every field has a built-in default (``DEFAULT_PROFILE``) and the
loader tolerates a missing file or absent keys, because classification runs in
places where no ``config/`` directory may exist (e.g. tests that point
``base_dir`` at a tmp dir, or a one-off ``classify_file`` on a loose PDF).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# Clause (ISO 14289 section) -> remediation class. Matched by longest prefix, so
# "7.18" also covers "7.18.1" etc. A clause with no mapping is "neutral".
DEFAULT_CLAUSE_CLASS: dict[str, str] = {
    "7.1": "auto",   # tagging / structure tree
    "7.2": "auto",   # general content tagging (paragraphs, lists)
    "7.3": "manual",  # tables: complex headers/spans need a human
    "7.4": "manual",  # heading hierarchy correctness
    "7.18": "manual",  # annotations / interactive content
}

# Structural signal -> class. Only "manual" hard-routes (beats clause + score).
DEFAULT_STRUCTURAL: dict[str, str] = {
    "image_only": "manual",
    "has_form": "manual",
    "complex_graphic": "manual",
}

# Weighted score (used only for the fuzzy middle band). All keys always present
# after loading -- the loader fills any the user omitted.
DEFAULT_SCORE: dict[str, float] = {
    "start": 100.0,
    "per_violation": 4.0,
    "per_neutral_clause": 8.0,
    "per_page_over": 0.0,
    "big_doc_pages": 100.0,
    "auto_threshold": 50.0,
    "borderline_band": 12.0,
}


@dataclass(frozen=True)
class ClassificationProfile:
    clause_class: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_CLAUSE_CLASS))
    structural: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_STRUCTURAL))
    score: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_SCORE))
    require_title_for_good: bool = False
    require_language_for_good: bool = False

    def class_for_clause(self, clause: str | int | None) -> str | None:
        """Return "auto"/"manual" for a clause, or ``None`` if unmapped (neutral).

        Longest-prefix match: "7.18.1" falls back to "7.18" then "7", so a single
        section mapping covers all of veraPDF's sub-clauses.
        """
        if clause is None:
            return None
        parts = str(clause).split(".")
        for i in range(len(parts), 0, -1):
            prefix = ".".join(parts[:i])
            if prefix in self.clause_class:
                return self.clause_class[prefix]
        return None

    def structural_override(self, signal: str) -> str | None:
        """Return the class for a structural signal (e.g. "manual"), or ``None``."""
        return self.structural.get(signal)


# Built-in fallback used when the config file is missing or unreadable.
DEFAULT_PROFILE = ClassificationProfile()


def load_classification_profile(
    path: str | os.PathLike | None,
) -> ClassificationProfile:
    """Load a :class:`ClassificationProfile` from YAML, defaulting on any gap.

    A missing ``path`` (or one pointing at a non-existent file) yields
    :data:`DEFAULT_PROFILE`; partial files fall back per key. Clause/structural
    keys are coerced to ``str`` (as :class:`IgnoreProfiles` does) so YAML ints
    round-trip cleanly; score keys merge over :data:`DEFAULT_SCORE`.
    """
    if not path or not Path(path).exists():
        return DEFAULT_PROFILE
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}

    clause_class = {
        str(clause): str(cls) for clause, cls in (data.get("clause_class") or {}).items()
    } or dict(DEFAULT_CLAUSE_CLASS)
    structural = {
        str(sig): str(cls) for sig, cls in (data.get("structural") or {}).items()
    } or dict(DEFAULT_STRUCTURAL)

    score = dict(DEFAULT_SCORE)
    for key, val in (data.get("score") or {}).items():
        try:
            score[str(key)] = float(val)
        except (TypeError, ValueError):
            continue

    good = data.get("good_to_go") or {}
    return ClassificationProfile(
        clause_class=clause_class,
        structural=structural,
        score=score,
        require_title_for_good=bool(good.get("require_title", False)),
        require_language_for_good=bool(good.get("require_language", False)),
    )
