from __future__ import annotations

import pytest
from typer.testing import CliRunner

from pdfscan.cli.app import app
from pdfscan.config import SessionError, load_settings
from pdfscan.config.sessions import load_sessions, resolve_session_root

# The autouse _isolate_sessions fixture (conftest.py) already points
# PDFSCAN_SESSIONS_FILE at a throwaway path, so load_sessions() reads/writes an
# isolated registry. Tests that need a different file set the env explicitly.


# --- registry CRUD ------------------------------------------------------------
def test_registry_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFSCAN_SESSIONS_FILE", str(tmp_path / "s.yaml"))
    reg = load_sessions()
    reg.add("clientA", tmp_path / "A", label="Client A", activate=True)
    reg.add("clientB", tmp_path / "B")
    reg.save()

    reloaded = load_sessions()
    assert {s.name for s in reloaded.list()} == {"clientA", "clientB"}
    assert reloaded.active == "clientA"
    assert reloaded.get("clientA").label == "Client A"
    assert reloaded.get("clientA").root == tmp_path / "A"
    assert reloaded.get("clientA").created_at  # stamped on add


def test_readd_preserves_created_at(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFSCAN_SESSIONS_FILE", str(tmp_path / "s.yaml"))
    reg = load_sessions()
    first = reg.add("a", tmp_path / "a")
    again = reg.add("a", tmp_path / "a2", label="renamed")
    assert again.created_at == first.created_at
    assert again.root == tmp_path / "a2"
    assert again.label == "renamed"


def test_remove_clears_active(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFSCAN_SESSIONS_FILE", str(tmp_path / "s.yaml"))
    reg = load_sessions()
    reg.add("a", tmp_path / "a", activate=True)
    reg.save()
    reg.remove("a")
    reg.save()
    assert load_sessions().active is None


def test_use_unknown_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFSCAN_SESSIONS_FILE", str(tmp_path / "s.yaml"))
    reg = load_sessions()
    with pytest.raises(SessionError):
        reg.use("ghost")


def test_empty_name_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFSCAN_SESSIONS_FILE", str(tmp_path / "s.yaml"))
    reg = load_sessions()
    with pytest.raises(SessionError):
        reg.add("   ", tmp_path / "x")


def test_stale_active_is_normalized(tmp_path, monkeypatch):
    f = tmp_path / "s.yaml"
    monkeypatch.setenv("PDFSCAN_SESSIONS_FILE", str(f))
    f.write_text("active: gone\nsessions: {}\n", encoding="utf-8")
    assert load_sessions().active is None  # active that names no session -> None


# --- resolution precedence ----------------------------------------------------
def test_resolve_precedence(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFSCAN_SESSIONS_FILE", str(tmp_path / "s.yaml"))
    reg = load_sessions()
    reg.add("active1", tmp_path / "active1", activate=True)
    reg.add("named", tmp_path / "named")
    reg.save()

    # active session is the fallback
    assert resolve_session_root() == ("active1", tmp_path / "active1")
    # an explicit name arg overrides the active session
    assert resolve_session_root(name="named") == ("named", tmp_path / "named")
    # an ad-hoc root overrides everything and carries no name
    assert resolve_session_root(root=str(tmp_path / "adhoc")) == (None, tmp_path / "adhoc")
    # env name is consulted before the active session...
    monkeypatch.setenv("PDFSCAN_SESSION", "named")
    assert resolve_session_root() == ("named", tmp_path / "named")
    # ...but an explicit arg still beats the env
    assert resolve_session_root(name="active1") == ("active1", tmp_path / "active1")


def test_resolve_none_when_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFSCAN_SESSIONS_FILE", str(tmp_path / "s.yaml"))
    assert resolve_session_root() == (None, None)


def test_resolve_unknown_name_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFSCAN_SESSIONS_FILE", str(tmp_path / "s.yaml"))
    with pytest.raises(SessionError):
        resolve_session_root(name="ghost")


# --- settings integration -----------------------------------------------------
def test_active_session_relocates_outputs(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFSCAN_SESSIONS_FILE", str(tmp_path / "s.yaml"))
    ws = tmp_path / "ws"
    reg = load_sessions()
    reg.add("audit", ws, activate=True)
    reg.save()

    s = load_settings(config_path=tmp_path / "missing.yaml")
    assert s.session_name == "audit"
    assert s.output_root == ws
    assert s.db_path == ws / "data" / "pdfscan.db"
    assert s.export_dir == ws / "exports"
    assert s.storage_root == ws / "remediation"
    assert s.output_paths()["session"] == "audit"


def test_session_arg_selects_inactive_session(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFSCAN_SESSIONS_FILE", str(tmp_path / "s.yaml"))
    reg = load_sessions()
    reg.add("x", tmp_path / "x")  # registered but not active
    reg.save()
    s = load_settings(config_path=tmp_path / "missing.yaml", session="x")
    assert s.session_name == "x"
    assert s.output_root == tmp_path / "x"


def test_explicit_output_root_beats_session(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFSCAN_SESSIONS_FILE", str(tmp_path / "s.yaml"))
    reg = load_sessions()
    reg.add("audit", tmp_path / "ws", activate=True)
    reg.save()
    s = load_settings(
        config_path=tmp_path / "missing.yaml",
        overrides={"paths": {"output_root": str(tmp_path / "explicit")}},
    )
    assert s.output_root == tmp_path / "explicit"
    assert s.session_name is None  # session not applied when an explicit root wins


# --- CLI ----------------------------------------------------------------------
def test_cli_session_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFSCAN_SESSIONS_FILE", str(tmp_path / "s.yaml"))
    runner = CliRunner()

    added = runner.invoke(app, ["session", "add", "clientA", str(tmp_path / "A"), "--use"])
    assert added.exit_code == 0, added.output
    assert (tmp_path / "A").is_dir()  # workspace created

    listed = runner.invoke(app, ["session", "list"])
    assert listed.exit_code == 0
    assert "* clientA" in listed.output

    shown = runner.invoke(app, ["session", "show"])
    assert shown.exit_code == 0
    assert "clientA" in shown.output
    assert str(tmp_path / "A") in shown.output  # resolved db/exports under the root

    cleared = runner.invoke(app, ["session", "use", "--clear"])
    assert cleared.exit_code == 0
    assert load_sessions().active is None

    removed = runner.invoke(app, ["session", "remove", "clientA"])
    assert removed.exit_code == 0
    assert "Removed" in removed.output


def test_cli_use_unknown_is_clean_error(tmp_path, monkeypatch):
    monkeypatch.setenv("PDFSCAN_SESSIONS_FILE", str(tmp_path / "s.yaml"))
    result = CliRunner().invoke(app, ["session", "use", "ghost"])
    assert result.exit_code == 1
    assert "unknown scan session" in result.output
