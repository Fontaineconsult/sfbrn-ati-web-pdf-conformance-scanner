"""Unit tests for veraPDF resolution and tool-availability checks (no network).

These cover the pure-Python resolution logic only; the actual download/install
is exercised manually (it requires Java and a ~30 MB installer).
"""

from __future__ import annotations

import os

from pdfscan.config import load_settings
from pdfscan.utils.tools_check import java_available
from pdfscan.verapdf_dist import installed_verapdf_path, resolve_verapdf


def _settings_with_verapdf_dir(tmp_path):
    """Build a Settings whose verapdf_dir points at an isolated tmp dir."""
    return load_settings(
        config_path=tmp_path / "missing.yaml",
        overrides={"paths": {"verapdf_dir": str(tmp_path)}},
    )


def _exe_name() -> str:
    return "verapdf.bat" if os.name == "nt" else "verapdf"


def test_resolve_returns_none_when_nothing_configured(tmp_path, monkeypatch):
    # Ensure no stray veraPDF on PATH or in env influences the result.
    monkeypatch.delenv("PDFSCAN_VERAPDF", raising=False)
    monkeypatch.setattr("shutil.which", lambda _name: None)

    settings = _settings_with_verapdf_dir(tmp_path)

    assert installed_verapdf_path(settings) is None
    assert resolve_verapdf(settings) is None


def test_installed_and_resolve_find_fake_launcher(tmp_path, monkeypatch):
    monkeypatch.delenv("PDFSCAN_VERAPDF", raising=False)
    monkeypatch.setattr("shutil.which", lambda _name: None)

    settings = _settings_with_verapdf_dir(tmp_path)

    fake = tmp_path / _exe_name()
    fake.write_text("echo fake-verapdf\n", encoding="utf-8")

    installed = installed_verapdf_path(settings)
    assert installed is not None
    assert installed == fake

    resolved = resolve_verapdf(settings)
    assert resolved == str(fake)


def test_explicit_command_takes_precedence(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)

    # A real file used as the explicit command.
    explicit = tmp_path / "custom-verapdf.bat"
    explicit.write_text("echo custom\n", encoding="utf-8")
    monkeypatch.setenv("PDFSCAN_VERAPDF", str(explicit))

    # Also drop an installed launcher; explicit command must still win.
    settings = _settings_with_verapdf_dir(tmp_path)
    (tmp_path / _exe_name()).write_text("echo installed\n", encoding="utf-8")

    assert resolve_verapdf(settings) == str(explicit)


def test_java_available_is_true_on_this_machine():
    result = java_available()
    assert isinstance(result, tuple)
    ok, version = result
    assert ok is True
    assert version is None or isinstance(version, str)
