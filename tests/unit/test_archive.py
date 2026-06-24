from __future__ import annotations

from pdfscan.pipeline.archive import ArchiveRules, explain, is_archived

RULES = ArchiveRules(
    keywords=["archive", "legacy", "deprecated"],
    path_segments=["/old/", "/archive/"],
    filename_prefixes=["legacy_", "old_"],
    filename_suffixes=["_old", "_legacy"],
)


def test_path_segment():
    assert explain("https://x.edu/archive/2019/a.pdf", RULES) == "path segment '/archive/'"


def test_filename_prefix():
    assert explain("https://x.edu/files/legacy_a.pdf", RULES).startswith("filename prefix")


def test_filename_suffix():
    assert explain("https://x.edu/files/report_old.pdf", RULES).startswith("filename suffix")


def test_keyword():
    assert explain("https://x.edu/deprecated-stuff/a.pdf", RULES).startswith("keyword")


def test_active_is_none():
    assert explain("https://x.edu/current/benefits.pdf", RULES) is None
    assert not is_archived("https://x.edu/current/benefits.pdf", RULES)


def test_url_decoded_path():
    assert explain("https://x.edu/%2Fold%2F/a.pdf", RULES) is not None
