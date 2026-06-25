"""CSV onboarding of site owners and responsible people (CSULA-style rosters).

Loads four optional CSVs into the normalized v4 tables. Tolerant of the real
data files, which (unlike the ``.example`` files) often lack headers and may pack
several comma-joined domains into one quoted cell:

* ``sites.csv``        -- ``Domain(s), Security_Group``: upsert owner + best-effort
                          link existing sites to it by host.
* ``employees.csv``    -- ``Full Name, Employee ID, Email``: upsert people.
* ``managers.csv``     -- one ``Employee ID`` per line: flag existing people.
* ``site_assignments`` -- ``Security_Group, Name, Employee ID, Email``: upsert
                          person + owner and link them (the many-to-many hinge).

Header rows are detected and skipped (an id/domain cell that isn't a digit /
doesn't contain a dot). Each function mutates a shared :class:`ImportReport` so
``run_import`` can report one summary, including which CSV domains could not be
matched to a crawl site (or matched ambiguously) for manual follow-up.
"""

from __future__ import annotations

import csv
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from pdfscan.db.repositories import (
    PersonRepository,
    SiteOwnerRepository,
    SiteRepository,
)
from pdfscan.models import Person, SiteOwner
from pdfscan.utils.urls import ensure_scheme, host_of, seed_hosts_from


@dataclass
class ImportReport:
    owners_created: int = 0
    people_created: int = 0
    managers_marked: int = 0
    memberships_added: int = 0
    sites_linked: int = 0
    sites_unmatched: list[str] = field(default_factory=list)  # no crawl site for host
    ambiguous: list[str] = field(default_factory=list)  # host shared by >1 site
    warnings: list[str] = field(default_factory=list)


def _rows(path: str | os.PathLike | None) -> list[list[str]]:
    """Non-empty rows of a CSV, or ``[]`` if the path is missing/``None``."""
    if path is None:
        return []
    p = Path(path)
    if not p.exists():
        return []
    with p.open(newline="", encoding="utf-8-sig") as fh:
        return [row for row in csv.reader(fh) if any(c.strip() for c in row)]


def _is_id(cell: str) -> bool:
    """True when a cell looks like a numeric employee id (header cells do not)."""
    cell = cell.strip()
    return bool(cell) and cell[0].isdigit()


def _host_key(domain: str) -> str:
    """Reduce a domain/URL cell to a comparable lowercased host (``www.`` stripped)."""
    value = domain.strip().strip('"')
    host = host_of(ensure_scheme(value)) if value else ""
    host = host or value.lower()
    return host[4:] if host.startswith("www.") else host


def _site_hosts(config) -> set[str]:
    return {h[4:] if h.startswith("www.") else h for h in seed_hosts_from(config)}


def import_sites_csv(conn: sqlite3.Connection, path, report: ImportReport) -> None:
    owners = SiteOwnerRepository(conn)
    sites = SiteRepository(conn)
    indexed = [(s, _site_hosts(s.config)) for s in sites.list()]
    for row in _rows(path):
        if len(row) < 2:
            continue
        group = row[-1].strip()
        # Everything before the last column is domain(s); a quoted cell may hold
        # several comma-joined domains, an unquoted one splits into columns.
        domains = [d.strip() for cell in row[:-1] for d in cell.split(",") if "." in d]
        if not group or not domains:
            continue  # header row ("Domain","Security_Group") or junk
        if owners.get_by_key(group) is None:
            report.owners_created += 1
        oid = owners.upsert(SiteOwner(id=None, key=group, label=group))
        for domain in domains:
            host = _host_key(domain)
            matches = [s for s, hosts in indexed if host in hosts]
            if len(matches) == 1:
                sites.set_owner(matches[0].name, oid)
                report.sites_linked += 1
            elif not matches:
                report.sites_unmatched.append(host)
            else:
                report.ambiguous.append(host)


def import_employees_csv(conn: sqlite3.Connection, path, report: ImportReport) -> None:
    people = PersonRepository(conn)
    for row in _rows(path):
        if len(row) < 2 or not _is_id(row[1]):
            continue  # header or blank/non-numeric id
        name = row[0].strip()
        emp_id = row[1].strip()
        email = row[2].strip() if len(row) > 2 and row[2].strip() else None
        if not name:
            continue
        if people.get_by_employee_id(emp_id) is None:
            report.people_created += 1
        people.upsert(Person(id=None, employee_id=emp_id, full_name=name, email=email))


def import_managers_csv(conn: sqlite3.Connection, path, report: ImportReport) -> None:
    people = PersonRepository(conn)
    for row in _rows(path):
        if not row or not _is_id(row[0]):
            continue  # header ("Manager ID") or blank
        emp_id = row[0].strip()
        if people.set_manager(emp_id, True):
            report.managers_marked += 1
        else:
            report.warnings.append(f"manager {emp_id} not found among people")


def import_assignments_csv(conn: sqlite3.Connection, path, report: ImportReport) -> None:
    owners = SiteOwnerRepository(conn)
    people = PersonRepository(conn)
    for row in _rows(path):
        if len(row) < 3 or not _is_id(row[2]):
            continue  # header or blank/non-numeric id
        group = row[0].strip()
        name = row[1].strip()
        emp_id = row[2].strip()
        email = row[3].strip() if len(row) > 3 and row[3].strip() else None
        if not group:
            continue
        if owners.get_by_key(group) is None:
            report.owners_created += 1
        oid = owners.upsert(SiteOwner(id=None, key=group, label=group))
        if people.get_by_employee_id(emp_id) is None:
            report.people_created += 1
        pid = people.upsert(
            Person(id=None, employee_id=emp_id, full_name=name or emp_id, email=email)
        )
        if people.add_membership(pid, oid):
            report.memberships_added += 1


def run_import(
    conn: sqlite3.Connection,
    *,
    sites=None,
    employees=None,
    managers=None,
    assignments=None,
) -> ImportReport:
    """Import any combination of the four CSVs (each optional) into one report.

    Order matters: owners + site links first, then people (from employees and
    from assignments, which also backfill owners/people), then manager flags
    LAST so every person — however introduced — is eligible to be flagged.
    """
    report = ImportReport()
    if sites is not None:
        import_sites_csv(conn, sites, report)
    if employees is not None:
        import_employees_csv(conn, employees, report)
    if assignments is not None:
        import_assignments_csv(conn, assignments, report)
    if managers is not None:
        import_managers_csv(conn, managers, report)
    return report
