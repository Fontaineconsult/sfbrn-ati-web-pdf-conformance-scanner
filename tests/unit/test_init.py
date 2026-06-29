from __future__ import annotations

from typer.testing import CliRunner

from pdfscan.cli.app import app
from pdfscan.config import load_sessions, load_settings
from pdfscan.service import ScannerService

# The autouse _isolate_sessions fixture isolates the session registry; tests that
# need to read it back set PDFSCAN_SESSIONS_FILE to their own tmp path.


def _svc(tmp_path):
    return ScannerService(load_settings(config_path=tmp_path / "missing.yaml"))


# --- facade core (quickstart) -------------------------------------------------
def test_quickstart_creates_session_db_and_sites(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFSCAN_SESSIONS_FILE", str(tmp_path / "s.yaml"))
    summary = _svc(tmp_path).quickstart(
        "clientA",
        tmp_path / "ws",
        label="Client A",
        sites=[{"name": "hr", "seeds": ["https://hr.sfsu.edu"]}],
    )
    assert summary["session"] == "clientA"
    assert summary["active"] is True
    assert summary["schema_version"] >= 4
    assert summary["sites_added"] == ["hr"]
    assert load_sessions().active == "clientA"
    assert (tmp_path / "ws" / "data" / "pdfscan.db").exists()


def test_quickstart_rebinds_settings_to_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFSCAN_SESSIONS_FILE", str(tmp_path / "s.yaml"))
    svc = _svc(tmp_path)
    svc.quickstart("a", tmp_path / "ws", sites=[{"name": "hr", "seeds": ["https://hr.sfsu.edu"]}])
    assert svc.settings.output_root == tmp_path / "ws"
    assert [s["name"] for s in svc.list_sites()] == ["hr"]  # reads the workspace DB


def test_quickstart_workspaces_are_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFSCAN_SESSIONS_FILE", str(tmp_path / "s.yaml"))
    _svc(tmp_path).quickstart("A", tmp_path / "A", sites=[{"name": "a", "seeds": ["https://a.example"]}])
    svc_b = _svc(tmp_path)
    svc_b.quickstart("B", tmp_path / "B")
    assert svc_b.list_sites() == []  # B's workspace has none of A's sites


# --- CLI wizard ---------------------------------------------------------------
def test_cli_init_noninteractive(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFSCAN_SESSIONS_FILE", str(tmp_path / "s.yaml"))
    result = CliRunner().invoke(
        app,
        [
            "init", "myscan", "--root", str(tmp_path / "ws"),
            "--site", "hr=https://hr.sfsu.edu",
            "--site", "news=https://news.example,https://news2.example",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Session 'myscan' is active" in result.output
    assert "+ site 'hr'" in result.output
    assert load_sessions().active == "myscan"
    assert (tmp_path / "ws" / "data" / "pdfscan.db").exists()


def test_cli_init_interactive_site_loop(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFSCAN_SESSIONS_FILE", str(tmp_path / "s.yaml"))
    # name via arg + root via flag; then the site loop: one site, then a blank line ends it.
    result = CliRunner().invoke(
        app,
        ["init", "guided", "--root", str(tmp_path / "ws")],
        input="hr\nhttps://hr.sfsu.edu\n\n",
    )
    assert result.exit_code == 0, result.output
    assert "+ added 'hr'" in result.output
    svc = ScannerService(load_settings(config_path=tmp_path / "missing.yaml", session="guided"))
    assert [s["name"] for s in svc.list_sites()] == ["hr"]


def test_cli_init_strips_bom_from_piped_input(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFSCAN_SESSIONS_FILE", str(tmp_path / "s.yaml"))
    # Windows stdin piping can prepend a U+FEFF BOM to the first line.
    result = CliRunner().invoke(
        app,
        ["init", "guided", "--root", str(tmp_path / "ws")],
        input="﻿hr\nhttps://hr.sfsu.edu\n\n",
    )
    assert result.exit_code == 0, result.output
    svc = ScannerService(load_settings(config_path=tmp_path / "missing.yaml", session="guided"))
    assert [s["name"] for s in svc.list_sites()] == ["hr"]  # cleaned, not "﻿hr"


def test_cli_init_bad_site_spec_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFSCAN_SESSIONS_FILE", str(tmp_path / "s.yaml"))
    result = CliRunner().invoke(
        app, ["init", "x", "--root", str(tmp_path / "ws"), "--site", "noequalsign"]
    )
    assert result.exit_code != 0
    assert "NAME=URL" in result.output


def _mock_doctor(monkeypatch, *, java, verapdf):
    monkeypatch.setattr(
        ScannerService,
        "doctor",
        lambda self: {
            "java": {"ok": java, "version": "1.8.0" if java else None},
            "verapdf": {"ok": verapdf, "version": "1.30.2" if verapdf else None},
            "playwright_chromium": True,
        },
    )


def test_cli_init_installs_verapdf_when_missing_and_yes(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFSCAN_SESSIONS_FILE", str(tmp_path / "s.yaml"))
    _mock_doctor(monkeypatch, java=True, verapdf=False)
    installed = {}
    monkeypatch.setattr(
        ScannerService,
        "setup_verapdf",
        lambda self, force=False: installed.setdefault("path", str(tmp_path / "verapdf.bat")),
    )
    result = CliRunner().invoke(
        app, ["init", "x", "--root", str(tmp_path / "ws"), "--site", "a=https://a.example", "--yes"]
    )
    assert result.exit_code == 0, result.output
    assert installed.get("path")  # install was attempted
    assert "veraPDF installed" in result.output


def test_cli_init_no_install_when_java_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFSCAN_SESSIONS_FILE", str(tmp_path / "s.yaml"))
    _mock_doctor(monkeypatch, java=False, verapdf=False)

    def fake_setup(self, force=False):
        raise AssertionError("veraPDF must not install without Java")

    monkeypatch.setattr(ScannerService, "setup_verapdf", fake_setup)
    result = CliRunner().invoke(
        app, ["init", "x", "--root", str(tmp_path / "ws"), "--site", "a=https://a.example", "--yes"]
    )
    assert result.exit_code == 0, result.output
    assert "Java: not found" in result.output
    assert "setup-verapdf" in result.output


def test_cli_init_noninteractive_skips_install_prompt(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFSCAN_SESSIONS_FILE", str(tmp_path / "s.yaml"))
    _mock_doctor(monkeypatch, java=True, verapdf=False)

    def fake_setup(self, force=False):
        raise AssertionError("must not install non-interactively without --yes")

    monkeypatch.setattr(ScannerService, "setup_verapdf", fake_setup)
    # No --yes and a non-interactive stdin -> no prompt, no install, no hang.
    result = CliRunner().invoke(
        app, ["init", "x", "--root", str(tmp_path / "ws"), "--site", "a=https://a.example"]
    )
    assert result.exit_code == 0, result.output
    assert "Install later" in result.output


def test_cli_init_reuses_existing_session(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFSCAN_SESSIONS_FILE", str(tmp_path / "s.yaml"))
    runner = CliRunner()
    runner.invoke(
        app, ["init", "dup", "--root", str(tmp_path / "ws1"), "--site", "a=https://a.example"]
    )
    # re-init with a different --root keeps the original workspace
    result = runner.invoke(
        app, ["init", "dup", "--root", str(tmp_path / "ws2"), "--site", "b=https://b.example"]
    )
    assert result.exit_code == 0, result.output
    assert "keeping its workspace" in result.output
    svc = ScannerService(load_settings(config_path=tmp_path / "missing.yaml", session="dup"))
    assert sorted(s["name"] for s in svc.list_sites()) == ["a", "b"]
