"""MCP tool handlers (framework-agnostic, fully testable without the ``mcp`` dep).

Every handler is wrapped by :func:`guard`, which (1) migrates the database on
first use so the tools work against a fresh or older DB, and (2) converts any
exception into a structured ``{"error", "error_type"}`` result so a tool call
never crashes the server. ``server.py`` is a thin FastMCP adapter that registers
these functions; their docstrings become the tool descriptions Claude sees.

Reactor-bound commands (crawl, full pipeline) run via the CLI in a subprocess --
Scrapy installs a Twisted reactor that must not share the MCP server's asyncio
loop. The subprocess inherits the server's resolved DB/config via env vars, so
it always reads and writes the same database the in-process tools do.
"""

from __future__ import annotations

import functools
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pdfscan.service import ScannerError, ScannerService

_SVC: ScannerService | None = None
_DB_READY = False

_EXPORT_EXT = {"csv": "csv", "json": "json", "excel": "xlsx", "html": "html"}


def _service() -> ScannerService:
    """Cached service (settings are loaded once per server process)."""
    global _SVC
    if _SVC is None:
        _SVC = ScannerService()
    return _SVC


def _ensure_db() -> None:
    """Migrate the configured DB to the current schema, once per process."""
    global _DB_READY
    if _DB_READY:
        return
    from pdfscan.db import migrate, session

    with session(_service().settings.db_path) as conn:
        migrate(conn)
    _DB_READY = True


def reset_state() -> None:
    """Drop cached service/DB state (test hook; safe to call anytime)."""
    global _SVC, _DB_READY
    _SVC = None
    _DB_READY = False


def guard(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a handler: migrate-on-first-use + never raise across the boundary."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            _ensure_db()
            return fn(*args, **kwargs)
        except ScannerError as exc:
            return {"error": str(exc), "error_type": "ScannerError"}
        except Exception as exc:  # tools must never crash the server
            return {"error": str(exc), "error_type": type(exc).__name__}

    return wrapper


def _cli(*args: str) -> dict:
    """Invoke the pdfscan CLI in a subprocess (for reactor-bound commands).

    The subprocess inherits the server's resolved DB path and config file via
    ``PDFSCAN_DB_PATH`` / ``PDFSCAN_CONFIG`` so it targets the same database.
    """
    settings = _service().settings
    env = dict(os.environ)
    env["PDFSCAN_DB_PATH"] = str(settings.db_path)
    if settings.config_path:
        env["PDFSCAN_CONFIG"] = str(settings.config_path)
    proc = subprocess.run(
        [sys.executable, "-m", "pdfscan", *args],
        capture_output=True,
        text=True,
        env=env,
    )
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "")[-4000:],
        "stderr": (proc.stderr or "")[-1500:],
    }


# === diagnostics =============================================================
@guard
def doctor() -> dict:
    """Report availability of Java, veraPDF, and Playwright Chromium."""
    return _service().doctor()


@guard
def db_status() -> dict:
    """Return the database path and current schema version."""
    from pdfscan.db import session
    from pdfscan.db.migrations import current_version

    settings = _service().settings
    with session(settings.db_path) as conn:
        version = current_version(conn)
    return {"db_path": str(settings.db_path), "schema_version": version}


@guard
def output_paths() -> dict:
    """Show where outputs are written: database, exports, remediation, scratch.

    Reflects any output_root / per-output overrides, so you can confirm files are
    being saved to the intended (possibly external) location before a run.
    """
    return _service().paths()


@guard
def setup_verapdf(force: bool = False) -> dict:
    """Download + install the bundled veraPDF if missing. Returns its path."""
    return {"verapdf": _service().setup_verapdf(force=force)}


# === sites ===================================================================
@guard
def list_sites() -> list[dict]:
    """List configured sites with scope, depth, seeds, and PDF counts."""
    return _service().list_sites()


@guard
def add_site(
    name: str,
    seeds: list[str],
    scope: str = "host",
    depth: int = 0,
    render_js: bool = False,
    include_external_pdfs: bool = False,
    allowed_hosts: list[str] | None = None,
    path_prefix: str | None = None,
    notes: str | None = None,
) -> dict:
    """Add or update a site to scan.

    scope = host | subdomain | domain | path. depth 0 = unlimited.
    render_js enables a Playwright (headless browser) render for JS-built pages.
    include_external_pdfs also captures PDFs hosted off the site's host.
    allowed_hosts overrides the hosts derived from the seeds (subdomain/domain
    scope). path_prefix restricts a path-scoped crawl. Returns the site id.
    """
    sid = _service().add_site(
        name,
        seeds,
        scope=scope,
        depth=depth,
        render_js=render_js,
        include_external_pdfs=include_external_pdfs,
        allowed_hosts=allowed_hosts,
        path_prefix=path_prefix,
        notes=notes,
    )
    return {"id": sid, "name": name}


@guard
def remove_site(name: str) -> dict:
    """Remove a site and its discovered PDFs."""
    return {"removed": _service().remove_site(name), "name": name}


@guard
def site_status(name: str) -> dict:
    """Coverage + accessibility + remediation-triage summary for a site.

    Includes discovered/verified counts, the three triage signals
    (good_to_go / fit_for_automated_tagging / needs_manual_remediation), and the
    site's owner + responsible people.
    """
    return _service().status(name)


@guard
def pdf_rules(name: str, url: str, limit: int = 5) -> dict:
    """veraPDF per-rule breakdown for PDFs whose URL contains ``url``.

    Shows each failing clause/test with its ignore-policy verdict (ignored /
    counts / a flag) so you can see *why* a PDF is non-compliant. ``url`` is a
    case-insensitive substring match; ``limit`` caps the PDFs shown.
    """
    return _service().pdf_rules(name, url, limit=limit)


# === crawl / verify / pipeline ===============================================
@guard
def crawl_site(
    name: str,
    max_pages: int | None = None,
    depth: int | None = None,
    timeout_s: int | None = None,
) -> dict:
    """Crawl a site for PDFs (runs in a subprocess; may take minutes).

    max_pages caps pages crawled; depth overrides the site's max depth;
    timeout_s stops the crawl after N seconds. Returns the CLI result.
    """
    args = ["crawl", name]
    if max_pages is not None:
        args += ["--max-pages", str(max_pages)]
    if depth is not None:
        args += ["--depth", str(depth)]
    if timeout_s is not None:
        args += ["--timeout", str(timeout_s)]
    return _cli(*args)


@guard
def verify_site(name: str, limit: int | None = None, refresh: bool = False) -> dict:
    """Download + veraPDF-verify a site's PDFs (may take minutes).

    limit verifies only the first N; refresh re-verifies already-reported PDFs
    (needed to populate newer signals). Returns verified/reused/failed counts.
    """
    return _service().verify(name, limit=limit, refresh=refresh)


@guard
def run_pipeline(
    name: str,
    limit: int | None = None,
    export: list[str] | None = None,
    check_404: bool = False,
) -> dict:
    """Full pipeline: crawl -> verify -> archive (-> export) in a subprocess.

    export accepts csv|json|excel|html (repeatable). check_404 also refreshes
    dead-link status. Long-running. Returns the CLI result.
    """
    args = ["run", name]
    if limit is not None:
        args += ["--limit", str(limit)]
    for fmt in export or []:
        args += ["--export", fmt]
    if check_404:
        args += ["--check-404"]
    return _cli(*args)


# === export / maintenance ====================================================
@guard
def export_results(name: str, fmt: str = "html", out: str | None = None) -> dict:
    """Export a site's results to csv | json | excel | html.

    ``html`` is a status-demarcated accessibility report. ``out`` may be omitted
    (defaults to ``<export_dir>/<site>.<ext>``) or relative (resolved under the
    configured export dir). Returns the row count and the written path.
    """
    svc = _service()
    fmt = (fmt or "html").lower()
    ext = _EXPORT_EXT.get(fmt, fmt)
    if out:
        p = Path(out)
        dest = p if p.is_absolute() else (svc.settings.export_dir / p)
    else:
        dest = svc.settings.export_dir / f"{name}.{ext}"
    return svc.export(fmt, dest, name=name)


@guard
def archive_site(name: str) -> dict:
    """Flag likely-archived PDFs for a site using the archive heuristics."""
    return {"archived": _service().archive(name), "name": name}


@guard
def check_404(name: str) -> dict:
    """Refresh dead-link (404) status for a site's PDFs and parent pages."""
    return _service().check_404(name)


@guard
def test_archive_rule(urls: list[str]) -> list[dict]:
    """Dry-run the archive heuristics against URLs (no scan)."""
    return _service().test_archive_rule(urls)


@guard
def evaluate_classifier(path: str, profile: str | None = None) -> dict:
    """Score the classifier against pre-sorted PDFs (calibration).

    ``path`` holds category subfolders (good_to_go / fit_for_automated_tagging /
    needs_manual_remediation, aliases accepted). ``profile`` optionally points at
    a candidate classification.yaml. Returns accuracy, a confusion matrix,
    per-class metrics, and the mismatch list.
    """
    return _service().evaluate(path, profile_path=profile)


# === ownership: owners =======================================================
@guard
def list_owners() -> list[dict]:
    """List site owners (org-level responsible groups) with member/site counts."""
    return _service().list_owners()


@guard
def add_owner(key: str, label: str | None = None, notes: str | None = None) -> dict:
    """Add or update a site owner (e.g. a department / content-manager group)."""
    return {"id": _service().add_owner(key, label=label, notes=notes), "key": key}


@guard
def show_owner(key: str) -> dict:
    """Show an owner's linked sites and member people, or an error if unknown."""
    detail = _service().show_owner(key)
    return detail if detail is not None else {"error": f"No such owner '{key}'"}


@guard
def remove_owner(key: str) -> dict:
    """Remove an owner (its sites are left without an owner; memberships drop)."""
    return {"removed": _service().remove_owner(key), "key": key}


@guard
def set_site_owner(name: str, owner_key: str | None = None) -> dict:
    """Assign a site's owner org by key, or clear it with owner_key=null."""
    _service().set_site_owner(name, owner_key)
    return {"site": name, "owner": owner_key}


@guard
def whois(name: str) -> dict:
    """Who is responsible for a site: owner org + member people (managers first)."""
    return _service().whois(name)


# === ownership: people =======================================================
@guard
def list_people() -> list[dict]:
    """List people with their email and manager flag."""
    return _service().list_people()


@guard
def add_person(
    employee_id: str, full_name: str, email: str | None = None, is_manager: bool = False
) -> dict:
    """Add or update a person (responsible individual)."""
    pid = _service().add_person(employee_id, full_name, email=email, is_manager=is_manager)
    return {"id": pid, "employee_id": employee_id}


@guard
def remove_person(employee_id: str) -> dict:
    """Remove a person and their owner memberships."""
    return {"removed": _service().remove_person(employee_id), "employee_id": employee_id}


@guard
def assign_person(employee_id: str, owner_key: str) -> dict:
    """Make a person a member of an owner org (idempotent)."""
    added = _service().assign_person(employee_id, owner_key)
    return {"assigned": added, "employee_id": employee_id, "owner": owner_key}


@guard
def unassign_person(employee_id: str, owner_key: str) -> dict:
    """Remove a person's membership in an owner org."""
    removed = _service().unassign_person(employee_id, owner_key)
    return {"removed": removed, "employee_id": employee_id, "owner": owner_key}


@guard
def import_people(
    sites: str | None = None,
    employees: str | None = None,
    managers: str | None = None,
    assignments: str | None = None,
) -> dict:
    """Bulk-import owners/people/assignments from CSV files (each path optional).

    sites.csv (Domain, Security_Group), employees.csv (Full Name, Employee ID,
    Email), managers.csv (one Employee ID per line), site_assignments.csv
    (Security_Group, Name, Employee ID, Email). Returns created counts plus any
    unmatched/ambiguous domains for follow-up.
    """
    return _service().import_people(
        sites=sites, employees=employees, managers=managers, assignments=assignments
    )


# All handlers, in a sensible presentation order, for the server to register.
TOOLS: list[Callable[..., Any]] = [
    doctor,
    db_status,
    output_paths,
    setup_verapdf,
    list_sites,
    add_site,
    remove_site,
    site_status,
    pdf_rules,
    crawl_site,
    verify_site,
    run_pipeline,
    export_results,
    archive_site,
    check_404,
    test_archive_rule,
    evaluate_classifier,
    list_owners,
    add_owner,
    show_owner,
    remove_owner,
    set_site_owner,
    whois,
    list_people,
    add_person,
    remove_person,
    assign_person,
    unassign_person,
    import_people,
]
