from __future__ import annotations

import pytest

from pdfscan.mcp import handlers


@pytest.fixture
def mcp_db(tmp_path, monkeypatch):
    """Point the cached service at a fresh tmp DB (auto-migrated on first call)."""
    monkeypatch.setenv("PDFSCAN_DB_PATH", str(tmp_path / "mcp.db"))
    handlers.reset_state()
    yield tmp_path
    handlers.reset_state()


def test_auto_migrate_brings_db_to_current_schema(mcp_db):
    st = handlers.db_status()
    assert st["schema_version"] == 4
    assert st["db_path"].endswith("mcp.db")


def test_guard_returns_error_instead_of_raising(mcp_db):
    res = handlers.site_status("does-not-exist")
    assert res["error_type"] == "ScannerError"
    assert "does-not-exist" in res["error"]


def test_unexpected_errors_are_also_caught(mcp_db, monkeypatch):
    # Force a non-ScannerError inside a handler; guard must still return a dict.
    monkeypatch.setattr(handlers, "_service", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    res = handlers.list_sites()
    assert res["error_type"] == "RuntimeError" and res["error"] == "boom"


def test_owner_person_whois_roundtrip(mcp_db):
    handlers.add_site("hr", ["https://hr.example.edu"])
    handlers.add_owner("grp", "HR group")
    handlers.add_person("e1", "Ann Boss", "ann@x", True)
    handlers.assign_person("e1", "grp")
    handlers.set_site_owner("hr", "grp")

    who = handlers.whois("hr")
    assert who["owner"] == "grp"
    assert who["responsible"][0]["name"] == "Ann Boss"
    assert who["responsible"][0]["is_manager"] is True
    assert any(o["key"] == "grp" for o in handlers.list_owners())


def test_assign_unknown_owner_is_structured_error(mcp_db):
    handlers.add_person("e1", "Ann", "a@x")
    res = handlers.assign_person("e1", "nope")
    assert res["error_type"] == "ScannerError"


def test_export_results_writes_through_handler(mcp_db, tmp_path):
    handlers.add_site("hr", ["https://hr.example.edu"])
    out = tmp_path / "report.html"
    res = handlers.export_results("hr", "html", str(out))
    assert res["rows"] == 0
    assert out.exists()
    assert out.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")


def test_tools_registry_is_complete_and_documented():
    # Every registered tool is callable and has a description (its docstring).
    assert len(handlers.TOOLS) >= 20
    names = {t.__name__ for t in handlers.TOOLS}
    assert {"site_status", "whois", "import_people", "pdf_rules", "export_results"} <= names
    for tool in handlers.TOOLS:
        assert (tool.__doc__ or "").strip(), f"{tool.__name__} is missing a description"
