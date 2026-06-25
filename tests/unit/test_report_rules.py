from __future__ import annotations

from pdfscan.db.repositories import ReportRepository
from pdfscan.models import PdfReport, ReportRule


def _seed_report(conn, pdf_hash: str = "h") -> ReportRepository:
    reps = ReportRepository(conn)
    reps.upsert(PdfReport(pdf_hash=pdf_hash))
    return reps


def test_replace_and_list_rules_round_trip(conn):
    reps = _seed_report(conn)
    n = reps.replace_rules(
        "h",
        [
            ReportRule("7.1", "3", status="FAILED", failed_checks=2, specification="ISO", description="d"),
            ReportRule("7.2", "10", failed_checks=1),
        ],
    )
    assert n == 2
    got = reps.list_rules("h")
    assert [(r.clause, r.test_number, r.failed_checks) for r in got] == [
        ("7.1", "3", 2),
        ("7.2", "10", 1),
    ]
    assert got[0].status == "FAILED"
    assert got[0].specification == "ISO"
    assert got[0].description == "d"


def test_replace_rules_supersedes_previous(conn):
    reps = _seed_report(conn)
    reps.replace_rules("h", [ReportRule("7.1", "3"), ReportRule("7.2", "10")])
    reps.replace_rules("h", [ReportRule("7.5", "1")])
    got = reps.list_rules("h")
    assert len(got) == 1 and got[0].clause == "7.5"


def test_list_rules_missing_hash_is_empty(conn):
    assert ReportRepository(conn).list_rules("nope") == []


def test_rules_cascade_when_report_deleted(conn):
    reps = _seed_report(conn)
    reps.replace_rules("h", [ReportRule("7.1", "3")])
    conn.execute("DELETE FROM pdf_report WHERE pdf_hash = 'h'")
    # FK ON DELETE CASCADE (engine enables PRAGMA foreign_keys=ON).
    assert reps.list_rules("h") == []
