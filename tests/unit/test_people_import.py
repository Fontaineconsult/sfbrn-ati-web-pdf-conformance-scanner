from __future__ import annotations

from pdfscan.db.repositories import PersonRepository, SiteOwnerRepository, SiteRepository
from pdfscan.models import Site, SiteConfig
from pdfscan.people import run_import


def _write(path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    return str(path)


def _add_site(conn, name: str, host: str) -> int:
    return SiteRepository(conn).add(
        Site(id=None, name=name, config=SiteConfig(seeds=[f"https://{host}"], allowed_hosts=[host]))
    )


# -- happy path: owners + people + managers + memberships + site link ----------
def test_full_import_links_and_resolves(conn, tmp_path):
    sid = _add_site(conn, "dprc", "dprc.sfsu.edu")
    sites_csv = _write(tmp_path / "sites.csv", "dprc.sfsu.edu,SFS-d-dprc\n")
    emp_csv = _write(
        tmp_path / "employees.csv",
        "Full Name,Employee ID,Email\nNolan Muna,917217917,nmuna@sfsu.edu\n",  # header skipped
    )
    mgr_csv = _write(tmp_path / "managers.csv", "Manager ID\n917217917\n")  # header skipped
    asn_csv = _write(
        tmp_path / "assign.csv", "SFS-d-dprc,Nolan Muna,917217917,nmuna@sfsu.edu\n"
    )

    rep = run_import(conn, sites=sites_csv, employees=emp_csv, managers=mgr_csv, assignments=asn_csv)

    assert rep.owners_created == 1
    assert rep.people_created == 1  # header row not counted
    assert rep.managers_marked == 1
    assert rep.memberships_added == 1
    assert rep.sites_linked == 1
    assert rep.sites_unmatched == [] and rep.ambiguous == []

    # the site now resolves its responsible person, flagged manager
    people = SiteRepository(conn).responsible_people(sid)
    assert [p.full_name for p in people] == ["Nolan Muna"]
    assert people[0].is_manager is True
    assert SiteRepository(conn).get_by_name("dprc").owner_id == \
        SiteOwnerRepository(conn).get_by_key("SFS-d-dprc").id


def test_missing_or_none_paths_are_noops(conn, tmp_path):
    rep = run_import(conn, sites=None, employees=str(tmp_path / "nope.csv"))
    assert rep.people_created == 0 and rep.owners_created == 0
    assert PersonRepository(conn).list() == []


def test_multi_domain_quoted_cell(conn, tmp_path):
    _add_site(conn, "aapi", "aapi.sfsu.edu")  # only one of the two domains is a known site
    sites_csv = _write(tmp_path / "sites.csv", '"aapi.sfsu.edu,aspire.sfsu.edu",SFS-d-aapi\n')
    rep = run_import(conn, sites=sites_csv)
    assert rep.owners_created == 1
    assert rep.sites_linked == 1            # aapi matched
    assert rep.sites_unmatched == ["aspire.sfsu.edu"]  # aspire has no crawl site


def test_ambiguous_host_is_not_linked(conn, tmp_path):
    _add_site(conn, "s1", "shared.example.edu")
    _add_site(conn, "s2", "shared.example.edu")  # two sites claim the same host
    sites_csv = _write(tmp_path / "sites.csv", "shared.example.edu,GRP\n")
    rep = run_import(conn, sites=sites_csv)
    assert rep.sites_linked == 0
    assert rep.ambiguous == ["shared.example.edu"]


def test_person_in_two_orgs_via_assignments(conn, tmp_path):
    asn_csv = _write(
        tmp_path / "assign.csv",
        "GRP-A,Multi Person,200500,mp@x.edu\nGRP-B,Multi Person,200500,mp@x.edu\n",
    )
    rep = run_import(conn, assignments=asn_csv)
    assert rep.people_created == 1
    assert rep.owners_created == 2
    assert rep.memberships_added == 2
    people = PersonRepository(conn)
    a = SiteOwnerRepository(conn).get_by_key("GRP-A")
    b = SiteOwnerRepository(conn).get_by_key("GRP-B")
    assert people.members_of(a.id)[0].employee_id == "200500"
    assert people.members_of(b.id)[0].employee_id == "200500"


def test_assignment_membership_dedup_on_reimport(conn, tmp_path):
    asn = "GRP-A,Solo,200600,s@x.edu\n"
    asn_csv = _write(tmp_path / "assign.csv", asn)
    run_import(conn, assignments=asn_csv)
    rep2 = run_import(conn, assignments=asn_csv)  # re-import: nothing new
    assert rep2.memberships_added == 0
    assert rep2.people_created == 0
    assert rep2.owners_created == 0
