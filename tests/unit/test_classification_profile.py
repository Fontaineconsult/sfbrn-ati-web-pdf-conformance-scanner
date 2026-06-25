from __future__ import annotations

from pdfscan.classify.profile import (
    DEFAULT_PROFILE,
    ClassificationProfile,
    load_classification_profile,
)


def test_missing_file_returns_default_profile(tmp_path):
    # status/export/eval may run where no config/ dir exists -> must not crash.
    prof = load_classification_profile(tmp_path / "nope.yaml")
    assert prof is DEFAULT_PROFILE
    assert load_classification_profile(None) is DEFAULT_PROFILE


def test_partial_yaml_falls_back_per_key(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("score:\n  auto_threshold: 80\n", encoding="utf-8")
    prof = load_classification_profile(p)
    # overridden key wins; omitted keys keep their defaults
    assert prof.score["auto_threshold"] == 80.0
    assert prof.score["start"] == 100.0
    assert prof.structural["image_only"] == "manual"


def test_clause_longest_prefix_match():
    prof = ClassificationProfile(clause_class={"7.18": "manual", "7": "auto"})
    assert prof.class_for_clause("7.18.6.2") == "manual"  # prefix 7.18 beats 7
    assert prof.class_for_clause("7.2") == "auto"          # falls back to 7
    assert prof.class_for_clause("9.1") is None            # unmapped -> neutral
    assert prof.class_for_clause(None) is None


def test_keys_coerced_to_str(tmp_path):
    # YAML may emit unquoted numeric clause/score keys.
    p = tmp_path / "c.yaml"
    p.write_text("clause_class:\n  7.3: manual\nscore:\n  per_violation: 5\n", encoding="utf-8")
    prof = load_classification_profile(p)
    assert prof.class_for_clause("7.3") == "manual"
    assert prof.score["per_violation"] == 5.0


def test_good_to_go_strictness_flags(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("good_to_go:\n  require_title: true\n  require_language: true\n", encoding="utf-8")
    prof = load_classification_profile(p)
    assert prof.require_title_for_good is True
    assert prof.require_language_for_good is True


def test_shipped_profile_parses():
    prof = load_classification_profile("config/classification.yaml")
    assert prof.structural["image_only"] == "manual"
    assert prof.class_for_clause("7.3") == "manual"
    assert prof.class_for_clause("7.1") == "auto"
    assert prof.score["auto_threshold"] == 50.0
