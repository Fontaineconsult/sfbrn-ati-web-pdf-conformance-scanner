from __future__ import annotations

from pathlib import Path

from pdfscan.config import load_settings


def test_defaults_when_config_missing(tmp_path):
    s = load_settings(config_path=tmp_path / "missing.yaml")
    assert s.get("crawl.default_scope") == "host"
    assert s.get("scrapy.obey_robots") is False
    assert s.get("scrapy.autothrottle.enabled") is True


def test_dot_get_default():
    s = load_settings(config_path=Path("definitely-missing.yaml"))
    assert s.get("a.b.c", "fallback") == "fallback"


def test_overrides_win(tmp_path):
    s = load_settings(
        config_path=tmp_path / "missing.yaml",
        overrides={"crawl": {"max_depth": 7}},
    )
    assert s.get("crawl.max_depth") == 7
    # untouched defaults remain
    assert s.get("crawl.default_scope") == "host"


def test_env_db_path_override(tmp_path, monkeypatch):
    target = tmp_path / "custom.db"
    monkeypatch.setenv("PDFSCAN_DB_PATH", str(target))
    s = load_settings(config_path=tmp_path / "missing.yaml")
    assert s.db_path == target


def test_relative_paths_resolve_against_base_dir(tmp_path):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "settings.yaml").write_text("database:\n  path: ./data/x.db\n", encoding="utf-8")
    s = load_settings(config_path=cfg_dir / "settings.yaml")
    # base_dir is the parent of config/, so ./data/x.db resolves under tmp_path
    assert s.db_path == tmp_path / "data" / "x.db"
