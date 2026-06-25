from __future__ import annotations

from pdfscan.db.repositories import (
    FailureRepository,
    PdfRepository,
    PersonRepository,
    ReportRepository,
    SiteOwnerRepository,
    SiteRepository,
)
from pdfscan.models import (
    DiscoveredPdf,
    Failure,
    PdfReport,
    Person,
    Site,
    SiteConfig,
    SiteOwner,
)

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


def test_list_unverified_skips_known_404(conn, sample_site):
    sid = SiteRepository(conn).add(sample_site)
    pdfs = PdfRepository(conn)
    ok = pdfs.upsert(DiscoveredPdf(PDF, PARENT, sid))
    gone = pdfs.upsert(DiscoveredPdf("https://hr.sfsu.edu/gone.pdf", PARENT, sid))
    pdfs.set_404(gone, pdf_404=True, parent_404=False)

    ids = {p.id for p in pdfs.list_unverified(sid)}
    assert ok in ids
    assert gone not in ids  # known-404 is skipped


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


def test_report_complex_graphic_round_trip(conn, sample_site):
    sid = SiteRepository(conn).add(sample_site)
    pdfs = PdfRepository(conn)
    pid = pdfs.upsert(DiscoveredPdf(PDF, PARENT, sid))
    pdfs.set_verified(pid, "hg", None)
    ReportRepository(conn).upsert(PdfReport(pdf_hash="hg", complex_graphic=True))
    assert ReportRepository(conn).get_by_hash("hg").complex_graphic is True
    assert pdfs.export_rows(sid)[0]["complex_graphic"] == 1


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


# -- ownership (v4) ------------------------------------------------------------
def test_owner_crud(conn):
    owners = SiteOwnerRepository(conn)
    oid = owners.upsert(SiteOwner(id=None, key="grp", label="Group"))
    assert owners.get_by_key("grp").id == oid
    # upsert by key updates label, does not duplicate
    owners.upsert(SiteOwner(id=None, key="grp", label="Renamed"))
    assert owners.get_by_id(oid).label == "Renamed"
    assert [o.key for o in owners.list()] == ["grp"]
    assert owners.remove("grp")
    assert owners.get_by_key("grp") is None


def test_person_crud_and_manager_flag(conn):
    people = PersonRepository(conn)
    pid = people.upsert(Person(id=None, employee_id="e1", full_name="Ann Lee", email="a@x"))
    assert people.get_by_employee_id("e1").id == pid
    assert people.get_by_employee_id("e1").is_manager is False
    assert people.set_manager("e1", True)
    assert people.get_by_id(pid).is_manager is True
    # upsert does not clear the manager flag
    people.upsert(Person(id=None, employee_id="e1", full_name="Ann Lee", email="a2@x"))
    assert people.get_by_id(pid).is_manager is True
    assert people.get_by_id(pid).email == "a2@x"
    assert people.remove("e1")


def test_membership_dedup_and_members_of(conn):
    owners = SiteOwnerRepository(conn)
    people = PersonRepository(conn)
    oid = owners.upsert(SiteOwner(id=None, key="grp"))
    p1 = people.upsert(Person(id=None, employee_id="e1", full_name="Boss", is_manager=True))
    p2 = people.upsert(Person(id=None, employee_id="e2", full_name="Aide"))
    people.add_membership(p1, oid)
    people.add_membership(p1, oid)  # idempotent
    people.add_membership(p2, oid)
    members = people.members_of(oid)
    assert [m.full_name for m in members] == ["Boss", "Aide"]  # manager first
    assert people.remove_membership(p2, oid)
    assert [m.employee_id for m in people.members_of(oid)] == ["e1"]


def test_person_in_multiple_orgs(conn):
    owners = SiteOwnerRepository(conn)
    people = PersonRepository(conn)
    a = owners.upsert(SiteOwner(id=None, key="a"))
    b = owners.upsert(SiteOwner(id=None, key="b"))
    p = people.upsert(Person(id=None, employee_id="e1", full_name="Multi"))
    people.add_membership(p, a)
    people.add_membership(p, b)
    assert people.members_of(a)[0].employee_id == "e1"
    assert people.members_of(b)[0].employee_id == "e1"


def test_responsible_people_for_site(conn, sample_site):
    sid = SiteRepository(conn).add(sample_site)
    owners = SiteOwnerRepository(conn)
    people = PersonRepository(conn)
    sites = SiteRepository(conn)
    oid = owners.upsert(SiteOwner(id=None, key="grp"))
    boss = people.upsert(Person(id=None, employee_id="e1", full_name="Boss", is_manager=True))
    aide = people.upsert(Person(id=None, employee_id="e2", full_name="Aide"))
    people.add_membership(boss, oid)
    people.add_membership(aide, oid)
    assert sites.responsible_people(sid) == []  # no owner yet
    assert sites.set_owner("hr", oid)
    names = [p.full_name for p in sites.responsible_people(sid)]
    assert names == ["Boss", "Aide"]  # manager first


def test_remove_owner_nulls_site_owner_id(conn, sample_site):
    SiteRepository(conn).add(sample_site)
    owners = SiteOwnerRepository(conn)
    sites = SiteRepository(conn)
    oid = owners.upsert(SiteOwner(id=None, key="grp"))
    sites.set_owner("hr", oid)
    assert sites.get_by_name("hr").owner_id == oid
    owners.remove("grp")  # FK ON DELETE SET NULL
    assert sites.get_by_name("hr").owner_id is None


def test_remove_site_keeps_memberships(conn, sample_site):
    SiteRepository(conn).add(sample_site)
    owners = SiteOwnerRepository(conn)
    people = PersonRepository(conn)
    sites = SiteRepository(conn)
    oid = owners.upsert(SiteOwner(id=None, key="grp"))
    p = people.upsert(Person(id=None, employee_id="e1", full_name="Solo"))
    people.add_membership(p, oid)
    sites.set_owner("hr", oid)
    assert sites.remove("hr")
    # membership is on the owner, not the site -> untouched
    assert [m.employee_id for m in people.members_of(oid)] == ["e1"]


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
