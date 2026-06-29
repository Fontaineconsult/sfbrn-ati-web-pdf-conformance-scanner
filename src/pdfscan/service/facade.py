"""ScannerService: high-level operations returning plain dict/JSON-friendly data.

This is the single place that wires the layers together. The CLI, an MCP server,
and a Skill are all thin adapters over these methods, so behavior stays identical
regardless of how pdfscan is driven.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from pdfscan.config import Settings, load_ignore_profiles, load_settings
from pdfscan.db import session
from pdfscan.db.repositories import (
    FailureRepository,
    PdfRepository,
    PersonRepository,
    ReportRepository,
    SiteOwnerRepository,
    SiteRepository,
)
from pdfscan.exporters import (
    collect_rows,
    export_csv,
    export_excel,
    export_html,
    export_json,
)
from pdfscan.models import Person, Site, SiteConfig, SiteOwner
from pdfscan.pipeline.archive import apply_archive_flags, explain, rules_from_settings
from pdfscan.utils.urls import ensure_scheme, host_of

_EXPORTERS = {"csv": export_csv, "json": export_json, "excel": export_excel, "html": export_html}


class ScannerError(RuntimeError):
    pass


class ScannerService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()

    # -- sites ------------------------------------------------------------------
    def add_site(
        self,
        name: str,
        seeds: list[str],
        *,
        scope: str = "host",
        depth: int = 0,
        render_js: bool = False,
        obey_robots: bool = False,
        include_external_pdfs: bool = False,
        resolvers: list[str] | None = None,
        allowed_hosts: list[str] | None = None,
        path_prefix: str | None = None,
        storage_template: str | None = None,
        notes: str | None = None,
    ) -> int:
        if scope not in {"host", "subdomain", "domain", "path"}:
            raise ScannerError("scope must be host|subdomain|domain|path")
        seeds = [ensure_scheme(s) for s in seeds if s and s.strip()]
        if not seeds:
            raise ScannerError("at least one non-empty seed URL is required")
        allowed = allowed_hosts or [h for h in (host_of(s) for s in seeds) if h]
        cfg = SiteConfig(
            seeds=list(seeds),
            allowed_hosts=allowed,
            scope=scope,
            max_depth=depth,
            render_js=render_js,
            obey_robots=obey_robots,
            include_external_pdfs=include_external_pdfs,
            resolvers=resolvers,
            path_prefix=path_prefix,
            storage_template=storage_template,
        )
        with session(self.settings.db_path) as conn:
            return SiteRepository(conn).upsert(Site(id=None, name=name, config=cfg, notes=notes))

    def list_sites(self) -> list[dict]:
        with session(self.settings.db_path) as conn:
            repo = SiteRepository(conn)
            pdfs = PdfRepository(conn)
            return [
                {
                    "name": s.name,
                    "scope": s.config.scope,
                    "depth": s.config.max_depth,
                    "seeds": s.config.seeds,
                    "enabled": s.enabled,
                    "pdfs": len(pdfs.list_by_site(s.id)),
                }
                for s in repo.list()
            ]

    def remove_site(self, name: str) -> bool:
        with session(self.settings.db_path) as conn:
            return SiteRepository(conn).remove(name)

    def _require_site(self, name: str) -> Site:
        with session(self.settings.db_path) as conn:
            site = SiteRepository(conn).get_by_name(name)
        if not site:
            raise ScannerError(f"No such site '{name}'")
        return site

    # -- crawl ------------------------------------------------------------------
    def crawl(self, name: str, overrides: dict[str, Any] | None = None) -> dict[str, int]:
        site = self._require_site(name)
        from pdfscan.scraper.runner import crawl_site

        return crawl_site(site, self.settings, overrides or None)

    # -- verify -----------------------------------------------------------------
    def _verapdf_cmd(self) -> str:
        from pdfscan.verapdf_dist import resolve_verapdf

        cmd = resolve_verapdf(self.settings)
        if not cmd:
            raise ScannerError("veraPDF not installed. Run setup_verapdf() / `pdfscan setup-verapdf`.")
        return cmd

    def _ignore_profiles(self):
        path = self.settings.resolve_path(
            self.settings.get("verapdf.ignore_profiles") or "config/ignore_profiles.yaml"
        )
        return load_ignore_profiles(path)

    def _classification_profile(self):
        from pdfscan.config import load_classification_profile

        path = self.settings.resolve_path(
            self.settings.get("classification.profile") or "config/classification.yaml"
        )
        return load_classification_profile(path)

    def verify(
        self, name: str, *, limit: int | None = None, save: bool = True, refresh: bool = False
    ) -> dict[str, int]:
        cmd = self._verapdf_cmd()
        ignore = self._ignore_profiles()
        from pdfscan.pdf.verify import verify_site

        with session(self.settings.db_path) as conn:
            site = SiteRepository(conn).get_by_name(name)
            if not site:
                raise ScannerError(f"No such site '{name}'")
            pdfs = PdfRepository(conn)
            rows = pdfs.list_by_site(site.id) if refresh else pdfs.list_unverified(site.id)
            if limit:
                rows = rows[:limit]
            template = site.config.storage_template or str(self.settings.get("storage.template"))
            return verify_site(
                conn, rows, self.settings, cmd, ignore,
                site_name=site.name, storage_template=template, save=save,
                workers=int(self.settings.get("verify.download_workers", 8)),
                batch_size=int(self.settings.get("verify.batch_size", 50)),
            )

    # -- maintenance ------------------------------------------------------------
    def archive(self, name: str) -> int:
        site = self._require_site(name)
        rules = rules_from_settings(self.settings)
        with session(self.settings.db_path) as conn:
            return apply_archive_flags(conn, site.id, rules)

    def test_archive_rule(self, urls: list[str]) -> list[dict]:
        rules = rules_from_settings(self.settings)
        return [{"url": u, "archived": explain(u, rules) is not None, "reason": explain(u, rules)} for u in urls]

    def check_404(self, name: str) -> dict[str, int]:
        site = self._require_site(name)
        from pdfscan.pipeline.status import refresh_404

        with session(self.settings.db_path) as conn:
            return refresh_404(conn, site.id, self.settings)

    def status(self, name: str) -> dict[str, Any]:
        from pdfscan.classify import Label, classify_rows

        ignore = self._ignore_profiles()
        profile = self._classification_profile()
        with session(self.settings.db_path) as conn:
            site = SiteRepository(conn).get_by_name(name)
            if not site:
                raise ScannerError(f"No such site '{name}'")
            rows = PdfRepository(conn).export_rows(site.id)
            n_fail = FailureRepository(conn).count_by_site(site.id)
            cls = classify_rows(conn, rows, ignore, profile)
            owner = SiteOwnerRepository(conn).get_by_id(site.owner_id) if site.owner_id else None
            responsible = [
                {"name": p.full_name, "email": p.email, "is_manager": p.is_manager}
                for p in SiteRepository(conn).responsible_people(site.id)
            ]
        verified = [r for r in rows if r["violations"] is not None]

        def _count(label: Label) -> int:
            return sum(1 for r in rows if cls[r["pdf_url"]].label is label)

        return {
            "site": name,
            "discovered": len(rows),
            "offsite": sum(1 for r in rows if r["offsite"]),
            "via_resolver": sum(1 for r in rows if r["via_resolver"]),
            "archived": sum(1 for r in rows if r["archived"]),
            "verified": len(verified),
            "untagged": sum(1 for r in verified if not r["tagged"]),
            "image_only": sum(1 for r in verified if r["image_only"]),
            "with_violations": sum(1 for r in verified if (r["violations"] or 0) > 0),
            "likely_passing": sum(1 for r in verified if (r["violations"] or 0) == 0 and r["tagged"]),
            "good_to_go": _count(Label.good_to_go),
            "fit_for_automated_tagging": _count(Label.fit_for_automated_tagging),
            "needs_manual_remediation": _count(Label.needs_manual_remediation),
            "owner": owner.key if owner else None,
            "owner_label": owner.label if owner else None,
            "responsible": responsible,
            "failures": n_fail,
        }

    def pdf_rules(self, name: str, url: str, *, limit: int = 5) -> dict[str, Any]:
        """Per-PDF veraPDF rule breakdown for PDFs whose URL contains ``url``.

        Each rule is annotated with the current ignore policy ("ignored" /
        "counts" / a flag), so an agent can see *why* a PDF fails and which
        clauses count toward its violations -- without re-running veraPDF.
        """
        ignore = self._ignore_profiles()
        with session(self.settings.db_path) as conn:
            site = SiteRepository(conn).get_by_name(name)
            if not site:
                raise ScannerError(f"No such site '{name}'")
            pdfs = PdfRepository(conn)
            reports = ReportRepository(conn)
            matches = [
                p for p in pdfs.list_by_site(site.id) if url.lower() in p.pdf_url.lower()
            ]
            shown = []
            for p in matches[:limit]:
                rules = reports.list_rules(p.file_hash) if p.file_hash else []
                counted = 0
                detail = []
                for r in rules:
                    ignored = ignore.is_ignored(r.clause, r.test_number)
                    flag = ignore.flag_for(r.clause, r.test_number)
                    if not ignored:
                        counted += 1
                    detail.append(
                        {
                            "clause": r.clause,
                            "test": r.test_number,
                            "failed_checks": r.failed_checks,
                            "policy": "ignored" if ignored else (flag or "counts"),
                            "description": r.description,
                        }
                    )
                shown.append(
                    {
                        "pdf_url": p.pdf_url,
                        "file_hash": p.file_hash,
                        "verified": bool(p.file_hash),
                        "counted_violations": counted,
                        "total_rules": len(rules),
                        "rules": detail,
                    }
                )
        return {"site": name, "query": url, "matched": len(matches), "pdfs": shown}

    # -- ownership (site owners + responsible people) ---------------------------
    def add_owner(self, key: str, *, label: str | None = None, notes: str | None = None) -> int:
        with session(self.settings.db_path) as conn:
            return SiteOwnerRepository(conn).upsert(
                SiteOwner(id=None, key=key, label=label, notes=notes)
            )

    def list_owners(self) -> list[dict]:
        with session(self.settings.db_path) as conn:
            owners = SiteOwnerRepository(conn)
            people = PersonRepository(conn)
            return [
                {
                    "key": o.key,
                    "label": o.label,
                    "members": len(people.members_of(o.id)),
                    "sites": len(owners.site_names(o.id)),
                }
                for o in owners.list()
            ]

    def show_owner(self, key: str) -> dict | None:
        with session(self.settings.db_path) as conn:
            owners = SiteOwnerRepository(conn)
            owner = owners.get_by_key(key)
            if not owner:
                return None
            members = PersonRepository(conn).members_of(owner.id)
            return {
                "key": owner.key,
                "label": owner.label,
                "notes": owner.notes,
                "sites": owners.site_names(owner.id),
                "members": [
                    {
                        "employee_id": p.employee_id,
                        "name": p.full_name,
                        "email": p.email,
                        "is_manager": p.is_manager,
                    }
                    for p in members
                ],
            }

    def remove_owner(self, key: str) -> bool:
        with session(self.settings.db_path) as conn:
            return SiteOwnerRepository(conn).remove(key)

    def add_person(
        self, employee_id: str, full_name: str, *, email: str | None = None, is_manager: bool = False
    ) -> int:
        with session(self.settings.db_path) as conn:
            return PersonRepository(conn).upsert(
                Person(
                    id=None,
                    employee_id=employee_id,
                    full_name=full_name,
                    email=email,
                    is_manager=is_manager,
                )
            )

    def list_people(self) -> list[dict]:
        with session(self.settings.db_path) as conn:
            return [
                {
                    "employee_id": p.employee_id,
                    "name": p.full_name,
                    "email": p.email,
                    "is_manager": p.is_manager,
                }
                for p in PersonRepository(conn).list()
            ]

    def remove_person(self, employee_id: str) -> bool:
        with session(self.settings.db_path) as conn:
            return PersonRepository(conn).remove(employee_id)

    def _resolve_membership(self, conn, employee_id: str, owner_key: str) -> tuple[int, int]:
        person = PersonRepository(conn).get_by_employee_id(employee_id)
        owner = SiteOwnerRepository(conn).get_by_key(owner_key)
        if not person:
            raise ScannerError(f"No such person '{employee_id}'")
        if not owner:
            raise ScannerError(f"No such owner '{owner_key}'")
        return person.id, owner.id

    def assign_person(self, employee_id: str, owner_key: str) -> bool:
        with session(self.settings.db_path) as conn:
            pid, oid = self._resolve_membership(conn, employee_id, owner_key)
            return PersonRepository(conn).add_membership(pid, oid)

    def unassign_person(self, employee_id: str, owner_key: str) -> bool:
        with session(self.settings.db_path) as conn:
            pid, oid = self._resolve_membership(conn, employee_id, owner_key)
            return PersonRepository(conn).remove_membership(pid, oid)

    def set_site_owner(self, site_name: str, owner_key: str | None) -> bool:
        """Assign (or clear, with ``owner_key=None``) a site's owner org by key."""
        with session(self.settings.db_path) as conn:
            owner_id: int | None = None
            if owner_key:
                owner = SiteOwnerRepository(conn).get_by_key(owner_key)
                if not owner:
                    raise ScannerError(f"No such owner '{owner_key}'")
                owner_id = owner.id
            if not SiteRepository(conn).set_owner(site_name, owner_id):
                raise ScannerError(f"No such site '{site_name}'")
            return True

    def whois(self, site_name: str) -> dict[str, Any]:
        """Owner + responsible people for a site (who to contact)."""
        with session(self.settings.db_path) as conn:
            site = SiteRepository(conn).get_by_name(site_name)
            if not site:
                raise ScannerError(f"No such site '{site_name}'")
            owner = SiteOwnerRepository(conn).get_by_id(site.owner_id) if site.owner_id else None
            responsible = [
                {
                    "employee_id": p.employee_id,
                    "name": p.full_name,
                    "email": p.email,
                    "is_manager": p.is_manager,
                }
                for p in SiteRepository(conn).responsible_people(site.id)
            ]
            return {
                "site": site_name,
                "owner": owner.key if owner else None,
                "owner_label": owner.label if owner else None,
                "responsible": responsible,
            }

    def import_people(
        self, *, sites=None, employees=None, managers=None, assignments=None
    ) -> dict[str, Any]:
        """Bulk-load owners/people/assignments from CSULA-style CSVs (each optional)."""
        from pdfscan.people import run_import

        with session(self.settings.db_path) as conn:
            report = run_import(
                conn, sites=sites, employees=employees, managers=managers, assignments=assignments
            )
        return dataclasses.asdict(report)

    # -- calibration ------------------------------------------------------------
    def evaluate(self, path: str | Path, *, profile_path: str | None = None) -> dict[str, Any]:
        """Score the classifier against pre-sorted PDFs under ``path``.

        ``path`` holds category subfolders (good_to_go / fit_for_automated_tagging
        / needs_manual_remediation, aliases accepted). Returns the eval report as
        a JSON-friendly dict (accuracy, confusion matrix, per-class metrics,
        mismatches). ``profile_path`` overrides the classification profile so a
        candidate YAML can be scored without editing the shipped one.
        """
        from pdfscan.classify.evaluate import evaluate as _evaluate
        from pdfscan.classify.evaluate import load_labeled_set

        cmd = self._verapdf_cmd()
        ignore = self._ignore_profiles()
        if profile_path:
            from pdfscan.config import load_classification_profile

            profile = load_classification_profile(self.settings.resolve_path(profile_path))
        else:
            profile = self._classification_profile()

        labeled = load_labeled_set(path)
        if not labeled:
            raise ScannerError(
                f"no labelled PDFs under '{path}' "
                "(expected category subfolders: good_to_go/, fit_for_automated_tagging/, "
                "needs_manual_remediation/)"
            )
        report = _evaluate(labeled, self.settings, cmd, ignore, profile)
        return report.to_dict()

    # -- export -----------------------------------------------------------------
    def export(
        self, fmt: str, out: str | Path, *, name: str | None = None, all_sites: bool = False
    ) -> dict[str, Any]:
        if fmt not in _EXPORTERS:
            raise ScannerError(f"unknown export format '{fmt}'")
        rows = collect_rows(self.settings, None if all_sites else name)
        path = _EXPORTERS[fmt](rows, out)
        return {"rows": len(rows), "path": str(path)}

    # -- veraPDF tooling --------------------------------------------------------
    def setup_verapdf(self, force: bool = False) -> str:
        from pdfscan.verapdf_dist import ensure_verapdf

        return ensure_verapdf(self.settings, force=force)

    def doctor(self) -> dict[str, Any]:
        from pdfscan.utils.tools_check import (
            java_available,
            playwright_chromium_installed,
            verapdf_available,
        )

        java_ok, java_ver = java_available()
        vera_ok, vera_ver = verapdf_available(self.settings)
        return {
            "java": {"ok": java_ok, "version": java_ver},
            "verapdf": {"ok": vera_ok, "version": vera_ver},
            "playwright_chromium": playwright_chromium_installed(),
        }

    def paths(self) -> dict[str, Any]:
        """Resolved output locations (database, exports, remediation, scratch, verapdf)."""
        return self.settings.output_paths()

    # -- easy mode --------------------------------------------------------------
    def quickstart(
        self,
        name: str,
        root: str | Path,
        *,
        label: str | None = None,
        sites: list[dict] | None = None,
        activate: bool = True,
        migrate: bool = True,
    ) -> dict[str, Any]:
        """Stand up a ready-to-use scan workspace in one call (the core of `init`).

        Registers (and by default activates) a named session at ``root``, creates
        the folder, migrates the session's database, and optionally adds ``sites``
        (each a dict with ``name`` + ``seeds`` and any extra ``add_site`` kwargs).
        This service's settings are re-pointed at the new workspace, so subsequent
        calls (e.g. :meth:`add_site`) target it. Returns a JSON-friendly summary.
        """
        from pdfscan.config import load_sessions
        from pdfscan.db import migrate as run_migrate

        registry = load_sessions()
        record = registry.add(name, root, label=label, activate=activate)
        registry.save()
        record.root.mkdir(parents=True, exist_ok=True)
        # Re-point this service at the session's workspace for the rest of the call.
        self.settings = load_settings(config_path=self.settings.config_path, session=record.name)
        version: int | None = None
        if migrate:
            with session(self.settings.db_path) as conn:
                version = run_migrate(conn)
        added: list[str] = []
        for spec in sites or []:
            extra = {k: v for k, v in spec.items() if k not in {"name", "seeds"}}
            self.add_site(spec["name"], spec["seeds"], **extra)
            added.append(spec["name"])
        return {
            "session": record.name,
            "root": str(record.root),
            "active": registry.active == record.name,
            "schema_version": version,
            "sites_added": added,
            "paths": self.settings.output_paths(),
        }

    # -- orchestration ----------------------------------------------------------
    def run(
        self,
        name: str,
        *,
        do_crawl: bool = True,
        do_verify: bool = True,
        do_archive: bool = True,
        do_404: bool = False,
        verify_limit: int | None = None,
        overrides: dict[str, Any] | None = None,
        exports: list[str] | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {"site": name}
        if do_crawl:
            result["crawl"] = self.crawl(name, overrides)
        if do_verify:
            try:
                result["verify"] = self.verify(name, limit=verify_limit)
            except ScannerError as exc:
                result["verify"] = {"skipped": str(exc)}
        if do_archive:
            result["archived"] = self.archive(name)
        if do_404:
            result["check_404"] = self.check_404(name)
        if exports:
            export_dir = self.settings.export_dir
            export_dir.mkdir(parents=True, exist_ok=True)
            ext = {"csv": "csv", "json": "json", "excel": "xlsx", "html": "html"}
            result["exports"] = {
                fmt: self.export(fmt, export_dir / f"{name}.{ext[fmt]}", name=name)["path"]
                for fmt in exports
            }
        return result
