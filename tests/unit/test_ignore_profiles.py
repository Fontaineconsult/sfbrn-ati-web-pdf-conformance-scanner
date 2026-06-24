from __future__ import annotations

from pdfscan.config import load_ignore_profiles


def test_ignore_and_flags(tmp_path):
    p = tmp_path / "ig.yaml"
    p.write_text(
        'ignore:\n  "5": ["1", "2"]\n'
        'immediate_failures:\n  "7.1":\n    "11": tagged\n    "3": image_only\n',
        encoding="utf-8",
    )
    ip = load_ignore_profiles(p)

    assert ip.is_ignored("5", "1")
    assert ip.is_ignored(5, 1)  # int coercion
    assert not ip.is_ignored("5", "3")
    assert ip.flag_for("7.1", "11") == "tagged"
    assert ip.flag_for("7.1", 3) == "image_only"
    assert ip.flag_for("7.1", "99") is None


def test_repo_ignore_profiles_load():
    # the shipped config file must parse
    ip = load_ignore_profiles("config/ignore_profiles.yaml")
    assert ip.flag_for("7.1", "11") == "tagged"
    assert ip.is_ignored("7.2", "10")
