from __future__ import annotations

from pdfscan.config import load_settings
from pdfscan.db import migrate, session
from pdfscan.service import ScannerService


def _service(tmp_path):
    settings = load_settings(
        config_path=tmp_path / "missing.yaml",
        overrides={"database": {"path": str(tmp_path / "t.db")}},
    )
    with session(settings.db_path) as conn:
        migrate(conn)
    return ScannerService(settings)


def test_add_and_list_site(tmp_path):
    svc = _service(tmp_path)
    svc.add_site("hr", ["https://hr.sfsu.edu"], scope="host", depth=2)
    sites = svc.list_sites()
    assert any(s["name"] == "hr" and s["scope"] == "host" for s in sites)


def test_test_archive_rule(tmp_path):
    svc = _service(tmp_path)
    res = svc.test_archive_rule(
        ["https://x/legacy_a.pdf", "https://x/current/b.pdf"]
    )
    assert res[0]["archived"] is True
    assert res[1]["archived"] is False


def test_status_empty_site(tmp_path):
    svc = _service(tmp_path)
    svc.add_site("hr", ["https://hr.sfsu.edu"])
    st = svc.status("hr")
    assert st["discovered"] == 0 and st["verified"] == 0
