"""Global settings: layered YAML + env + built-in defaults with dot-notation access.

Precedence (highest first): explicit overrides (CLI) > env (PDFSCAN_*) > settings.yaml
> built-in DEFAULTS. Relative data paths resolve against the project root (the parent
of the directory containing settings.yaml), so the tool works from any CWD.
"""

from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

DEFAULTS: dict[str, Any] = {
    "database": {"path": "./data/pdfscan.db", "wal": True, "busy_timeout_ms": 30000},
    "paths": {
        "temp_dir": "./.scratch",
        "export_dir": "./exports",
        "verapdf_dir": "./vendor/verapdf",
    },
    "crawl": {"default_scope": "host", "include_external_pdfs": False, "max_depth": 0},
    "scrapy": {
        "user_agent": "pdfscan/0.1 (+https://github.com/sfbrn/pdfscan)",
        "obey_robots": False,
        "download_delay": 0.5,
        "concurrent_requests": 16,
        "concurrent_requests_per_domain": 4,
        "autothrottle": {
            "enabled": True,
            "start_delay": 5,
            "max_delay": 60,
            "target_concurrency": 1.0,
        },
        "playwright": {
            "enabled_default": False,
            "browser": "chromium",
            "headless": True,
            "wait_until": "networkidle",
            "timeout_ms": 30000,
        },
    },
    "verapdf": {
        "version": "1.26.2",
        "installer_url": "https://software.verapdf.org/releases/verapdf-installer.zip",
        "flavour": "ua1",
        "timeout": 180,
    },
    "download": {"timeout": 30, "ssl_insecure_retry": True, "max_bytes": 524288000},
    "verify": {"download_workers": 8, "batch_size": 50, "batch_timeout": 1800},
    "classification": {"profile": "./config/classification.yaml"},
    "storage": {"root": "./remediation", "template": "{root}/{site}/{hash}.pdf"},
    "resolvers": {"enabled": ["box"]},
    "archive": {
        "keywords": [
            "archive",
            "archived",
            "legacy",
            "deprecated",
            "obsolete",
            "historical",
            "outdated",
            "past-events",
        ],
        "path_segments": ["/old/", "/archive/", "/archived/", "/legacy/", "/backup/", "/previous/"],
        "filename_prefixes": ["archived_", "old_", "legacy_", "deprecated_"],
        "filename_suffixes": ["_archived", "_old", "_legacy", "_deprecated"],
    },
    "logging": {"level": "INFO"},
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = deepcopy(base)
    for key, val in (override or {}).items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = deepcopy(val)
    return out


def resolve_config_path(explicit: str | os.PathLike | None = None) -> Path | None:
    """Find settings.yaml: explicit arg > PDFSCAN_CONFIG > walk up CWD for config/settings.yaml."""
    if explicit:
        return Path(explicit)
    env = os.environ.get("PDFSCAN_CONFIG")
    if env:
        return Path(env)
    here = Path.cwd()
    for folder in [here, *here.parents]:
        candidate = folder / "config" / "settings.yaml"
        if candidate.exists():
            return candidate
    return None


def _base_dir_for(config_path: Path | None) -> Path:
    if config_path is None:
        return Path.cwd()
    parent = config_path.resolve().parent
    # config/settings.yaml -> project root is the parent of config/
    return parent.parent if parent.name == "config" else parent


@dataclass(frozen=True)
class Settings:
    raw: dict[str, Any]
    base_dir: Path = field(default_factory=Path.cwd)
    config_path: Path | None = None

    def get(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self.raw
        for part in dotted.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return default
        return cur

    def resolve_path(self, value: str | os.PathLike) -> Path:
        p = Path(value)
        return p if p.is_absolute() else (self.base_dir / p)

    # --- convenience accessors -------------------------------------------------
    @property
    def db_path(self) -> Path:
        env = os.environ.get("PDFSCAN_DB_PATH")
        return self.resolve_path(env or self.get("database.path", "./data/pdfscan.db"))

    @property
    def temp_dir(self) -> Path:
        return self.resolve_path(self.get("paths.temp_dir", "./.scratch"))

    @property
    def export_dir(self) -> Path:
        return self.resolve_path(self.get("paths.export_dir", "./exports"))

    @property
    def verapdf_dir(self) -> Path:
        return self.resolve_path(self.get("paths.verapdf_dir", "./vendor/verapdf"))

    @property
    def storage_root(self) -> Path:
        env = os.environ.get("PDFSCAN_STORAGE_ROOT")
        return self.resolve_path(env or self.get("storage.root", "./remediation"))

    @property
    def verapdf_command(self) -> str | None:
        """Explicit veraPDF executable path, if configured via env/yaml (else None -> autodetect)."""
        env = os.environ.get("PDFSCAN_VERAPDF")
        return env or self.get("verapdf.command")


def load_settings(
    config_path: str | os.PathLike | None = None,
    overrides: dict[str, Any] | None = None,
) -> Settings:
    """Load layered settings. ``overrides`` (e.g. from CLI flags) win over everything."""
    load_dotenv()
    path = resolve_config_path(config_path)
    raw = deepcopy(DEFAULTS)
    if path and path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        raw = _deep_merge(raw, loaded)
    if overrides:
        raw = _deep_merge(raw, overrides)
    return Settings(raw=raw, base_dir=_base_dir_for(path), config_path=path)
