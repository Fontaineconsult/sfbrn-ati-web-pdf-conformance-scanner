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


# --- custom output locations --------------------------------------------------
def test_output_root_relocates_all_outputs(tmp_path):
    out = tmp_path / "out"
    s = load_settings(
        config_path=tmp_path / "missing.yaml",
        overrides={"paths": {"output_root": str(out)}},
    )
    assert s.output_root == out
    assert s.db_path == out / "data" / "pdfscan.db"
    assert s.export_dir == out / "exports"
    assert s.storage_root == out / "remediation"
    assert s.temp_dir == out / ".scratch"
    # veraPDF is vendored tooling (an input) -> stays under the project, not output_root
    assert s.verapdf_dir == s.base_dir / "vendor" / "verapdf"


def test_output_root_env_override(tmp_path, monkeypatch):
    out = tmp_path / "envout"
    monkeypatch.setenv("PDFSCAN_OUTPUT_ROOT", str(out))
    s = load_settings(config_path=tmp_path / "missing.yaml")
    assert s.output_root == out
    assert s.export_dir == out / "exports"


def test_per_output_env_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFSCAN_EXPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("PDFSCAN_STORAGE_ROOT", str(tmp_path / "pdfs"))
    monkeypatch.setenv("PDFSCAN_TEMP_DIR", str(tmp_path / "tmp"))
    s = load_settings(config_path=tmp_path / "missing.yaml")
    assert s.export_dir == tmp_path / "reports"
    assert s.storage_root == tmp_path / "pdfs"
    assert s.temp_dir == tmp_path / "tmp"


def test_absolute_output_path_ignores_output_root(tmp_path):
    abs_db = tmp_path / "elsewhere" / "my.db"
    s = load_settings(
        config_path=tmp_path / "missing.yaml",
        overrides={
            "paths": {"output_root": str(tmp_path / "out")},
            "database": {"path": str(abs_db)},
        },
    )
    assert s.db_path == abs_db


def test_no_output_root_is_backward_compatible(tmp_path):
    s = load_settings(config_path=tmp_path / "missing.yaml")
    assert s.output_root is None
    assert s.export_dir == s.base_dir / "exports"  # unchanged from prior behavior


def test_output_paths_summary(tmp_path):
    out = tmp_path / "out"
    s = load_settings(
        config_path=tmp_path / "missing.yaml",
        overrides={"paths": {"output_root": str(out)}},
    )
    summary = s.output_paths()
    assert summary["output_root"] == str(out)
    assert summary["exports"] == str(out / "exports")
    assert summary["database"].endswith("pdfscan.db")
