"""ScannerService: high-level operations returning plain dict/JSON-friendly data.

This is the single place that wires the layers together. The CLI, an MCP server,
and a Skill are all thin adapters over these methods, so behavior stays identical
regardless of how pdfscan is driven.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pdfscan.config import Settings, load_ignore_profiles, load_settings
from pdfscan.db import session
from pdfscan.db.repositories import FailureRepository, PdfRepository, SiteRepository
from pdfscan.exporters import collect_rows, export_csv, export_excel, export_json
from pdfscan.models import Site, SiteConfig
from pdfscan.pipeline.archive import apply_archive_flags, explain, rules_from_settings
from pdfscan.utils.urls import host_of

_EXPORTERS = {"csv": export_csv, "json": export_json, "excel": export_excel}


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

    def verify(
        self, name: str, *, limit: int | None = None, save: bool = True, refresh: bool = False
    ) -> dict[str, int]:
        cmd = self._verapdf_cmd()
        ignore = self._ignore_profiles()
        from pdfscan.pdf.verify import verify_pdf

        counts = {"verified": 0, "reused": 0, "failed": 0}
        with session(self.settings.db_path) as conn:
            site = SiteRepository(conn).get_by_name(name)
            if not site:
                raise ScannerError(f"No such site '{name}'")
            pdfs = PdfRepository(conn)
            rows = pdfs.list_by_site(site.id) if refresh else pdfs.list_unverified(site.id)
            if limit:
                rows = rows[:limit]
            template = site.config.storage_template or str(self.settings.get("storage.template"))
            for pdf in rows:
                outcome = verify_pdf(
                    conn, pdf, self.settings, cmd, ignore,
                    site_name=site.name, storage_template=template, save=save,
                )
                counts[outcome.status] = counts.get(outcome.status, 0) + 1
                conn.commit()
        return counts

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
        with session(self.settings.db_path) as conn:
            site = SiteRepository(conn).get_by_name(name)
            if not site:
                raise ScannerError(f"No such site '{name}'")
            rows = PdfRepository(conn).export_rows(site.id)
            n_fail = FailureRepository(conn).count_by_site(site.id)
        verified = [r for r in rows if r["violations"] is not None]
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
            "failures": n_fail,
        }

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
            ext = {"csv": "csv", "json": "json", "excel": "xlsx"}
            result["exports"] = {
                fmt: self.export(fmt, export_dir / f"{name}.{ext[fmt]}", name=name)["path"]
                for fmt in exports
            }
        return result
