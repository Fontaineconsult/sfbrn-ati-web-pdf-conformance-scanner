from __future__ import annotations

from pdfscan.db.repositories import (
    FailureRepository,
    PdfRepository,
    ReportRepository,
    SiteRepository,
)
from pdfscan.models import DiscoveredPdf, Failure, PdfReport, Site, SiteConfig

PARENT = "https://hr.sfsu.edu/"
PDF = "https://hr.sfsu.edu/a.pdf"


def test_site_crud(conn, sample_site):
    repo = SiteRepository(conn)
    sid = repo.add(sample_site)
    got = repo.get_by_name("hr")
    assert got is not None and got.id == sid
    assert got.config.seeds == ["https://hr.sfsu.edu"]
    assert got.config.max_depth == 3
    assert [s.name for s in repo.list()] == ["hr"]
    assert repo.remove("hr")
    assert repo.get_by_name("hr") is None


def test_site_upsert_updates_config(conn):
    repo = SiteRepository(conn)
    repo.upsert(Site(id=None, name="hr", config=SiteConfig(seeds=["u"])))
    repo.upsert(Site(id=None, name="hr", config=SiteConfig(seeds=["u"], max_depth=9)))
    got = repo.get_by_name("hr")
    assert got.config.max_depth == 9
    assert len(repo.list()) == 1


def test_pdf_dedup_and_unverified(conn, sample_site):
    sid = SiteRepository(conn).add(sample_site)
    pdfs = PdfRepository(conn)
    id1 = pdfs.upsert(DiscoveredPdf(PDF, PARENT, sid))
    id2 = pdfs.upsert(DiscoveredPdf(PDF, PARENT, sid))
    assert id1 == id2  # dedup on (pdf_url, parent_url)
    assert pdfs.exists(PDF, PARENT)
    assert len(pdfs.list_unverified(sid)) == 1

    ReportRepository(conn).upsert(PdfReport(pdf_hash="h1", violations=2))
    pdfs.set_verified(id1, "h1", "/tmp/a.pdf")
    assert pdfs.list_unverified(sid) == []
    assert pdfs.get(id1).local_path == "/tmp/a.pdf"


def test_offsite_flag_persisted(conn, sample_site):
    sid = SiteRepository(conn).add(sample_site)
    pdfs = PdfRepository(conn)
    pid = pdfs.upsert(DiscoveredPdf("https://cdn.other.com/x.pdf", PARENT, sid, offsite=True))
    assert pdfs.get(pid).offsite is True


def test_report_upsert_overwrite(conn):
    reps = ReportRepository(conn)
    reps.upsert(PdfReport(pdf_hash="h", violations=1))
    reps.upsert(PdfReport(pdf_hash="h", violations=9))
    assert reps.get_by_hash("h").violations == 9
    assert reps.exists_for_hash("h")


def test_report_upsert_no_overwrite(conn):
    reps = ReportRepository(conn)
    reps.upsert(PdfReport(pdf_hash="h", violations=1))
    reps.upsert(PdfReport(pdf_hash="h", violations=9), overwrite=False)
    assert reps.get_by_hash("h").violations == 1


def test_failures(conn, sample_site):
    sid = SiteRepository(conn).add(sample_site)
    f = FailureRepository(conn)
    f.add(Failure(site_id=sid, pdf_id=None, error_message="boom"))
    assert f.count_by_site(sid) == 1
    assert f.list_by_site(sid)[0].error_message == "boom"


def test_export_rows_join(conn, sample_site):
    sid = SiteRepository(conn).add(sample_site)
    pdfs = PdfRepository(conn)
    pid = pdfs.upsert(DiscoveredPdf(PDF, PARENT, sid))
    pdfs.set_verified(pid, "h1", None)
    ReportRepository(conn).upsert(PdfReport(pdf_hash="h1", violations=3, tagged=True, page_count=5))
    rows = pdfs.export_rows(sid)
    assert len(rows) == 1
    assert rows[0]["site"] == "hr"
    assert rows[0]["violations"] == 3
    assert rows[0]["tagged"] == 1
    assert rows[0]["page_count"] == 5
