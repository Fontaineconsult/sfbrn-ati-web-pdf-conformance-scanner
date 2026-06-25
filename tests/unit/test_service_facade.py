from __future__ import annotations

import pytest

from pdfscan.config import load_settings
from pdfscan.db import migrate, session
from pdfscan.service import ScannerError, ScannerService


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
    # triage keys exist even with nothing verified
    assert st["good_to_go"] == 0
    assert st["fit_for_automated_tagging"] == 0
    assert st["needs_manual_remediation"] == 0


def test_status_triage_counts(tmp_path):
    from pdfscan.db.repositories import PdfRepository, ReportRepository, SiteRepository
    from pdfscan.models import DiscoveredPdf, PdfReport

    svc = _service(tmp_path)
    svc.add_site("hr", ["https://hr.sfsu.edu"])
    with session(svc.settings.db_path) as conn:
        sid = SiteRepository(conn).get_by_name("hr").id
        pdfs = PdfRepository(conn)
        reps = ReportRepository(conn)
        seed = [
            ("https://hr.sfsu.edu/good.pdf", "g", PdfReport(pdf_hash="g", violations=0, tagged=True)),
            ("https://hr.sfsu.edu/scan.pdf", "s",
             PdfReport(pdf_hash="s", violations=1, tagged=True, image_only=True)),
            ("https://hr.sfsu.edu/untag.pdf", "u",
             PdfReport(pdf_hash="u", violations=1, tagged=False)),
        ]
        for url, h, report in seed:
            pid = pdfs.upsert(DiscoveredPdf(url, "https://hr.sfsu.edu/", sid))
            pdfs.set_verified(pid, h, None)
            reps.upsert(report)
        conn.commit()

    st = svc.status("hr")
    assert st["verified"] == 3
    assert st["good_to_go"] == 1               # tagged + 0 violations
    assert st["needs_manual_remediation"] == 1  # image-only / scanned
    assert st["fit_for_automated_tagging"] == 1  # untagged, low violations


# -- ownership ----------------------------------------------------------------
def _seed_owned_site(svc):
    svc.add_site("hr", ["https://hr.sfsu.edu"])
    svc.add_owner("grp", label="HR Web")
    svc.add_person("e1", "Ann Boss", email="ann@x", is_manager=True)
    svc.add_person("e2", "Ben Aide", email="ben@x")
    svc.assign_person("e1", "grp")
    svc.assign_person("e2", "grp")
    svc.set_site_owner("hr", "grp")


def test_owner_assign_and_whois(tmp_path):
    svc = _service(tmp_path)
    _seed_owned_site(svc)
    who = svc.whois("hr")
    assert who["owner"] == "grp" and who["owner_label"] == "HR Web"
    assert [p["name"] for p in who["responsible"]] == ["Ann Boss", "Ben Aide"]  # manager first
    assert who["responsible"][0]["is_manager"] is True


def test_status_includes_owner_and_responsible(tmp_path):
    svc = _service(tmp_path)
    _seed_owned_site(svc)
    st = svc.status("hr")
    assert st["owner"] == "grp"
    assert st["owner_label"] == "HR Web"
    assert {p["name"] for p in st["responsible"]} == {"Ann Boss", "Ben Aide"}


def test_list_and_show_owner(tmp_path):
    svc = _service(tmp_path)
    _seed_owned_site(svc)
    owners = svc.list_owners()
    assert owners == [{"key": "grp", "label": "HR Web", "members": 2, "sites": 1}]
    detail = svc.show_owner("grp")
    assert detail["sites"] == ["hr"]
    assert {m["employee_id"] for m in detail["members"]} == {"e1", "e2"}


def test_set_site_owner_validation(tmp_path):
    svc = _service(tmp_path)
    svc.add_site("hr", ["https://hr.sfsu.edu"])
    with pytest.raises(ScannerError):
        svc.set_site_owner("hr", "nope")     # unknown owner
    with pytest.raises(ScannerError):
        svc.set_site_owner("nosite", None)   # unknown site


def test_remove_owner_clears_site(tmp_path):
    svc = _service(tmp_path)
    _seed_owned_site(svc)
    assert svc.remove_owner("grp")
    assert svc.whois("hr")["owner"] is None      # FK SET NULL
    assert svc.whois("hr")["responsible"] == []
