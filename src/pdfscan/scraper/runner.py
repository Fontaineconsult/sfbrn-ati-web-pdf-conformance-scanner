"""Run the generic spider for a single site in its own CrawlerProcess.

Scrapy's reactor cannot be restarted within a process, so one ``crawl_site`` call
== one ``CrawlerProcess.start()``. Crawling multiple sites is done by the caller
invoking this once per site (e.g. a subprocess per site for ``crawl --all``).
"""

from __future__ import annotations

from typing import Any

from pdfscan.config import Settings
from pdfscan.db import session
from pdfscan.db.repositories import PdfRepository
from pdfscan.models import Site
from pdfscan.resolvers import default_registry
from pdfscan.scraper.settings import build_scrapy_settings
from pdfscan.scraper.spider import GenericPdfSpider


def crawl_site(
    site: Site,
    settings: Settings,
    run_overrides: dict[str, Any] | None = None,
) -> dict[str, int]:
    """Crawl one site. Blocks until the crawl completes. Returns simple stats."""
    from scrapy.crawler import CrawlerProcess

    scrapy_settings = build_scrapy_settings(site, settings, run_overrides)
    enabled = site.config.resolvers or settings.get("resolvers.enabled")
    registry = default_registry(enabled)

    before = _pdf_count(settings, site.id)

    process = CrawlerProcess(settings=scrapy_settings)
    process.crawl(
        GenericPdfSpider,
        site=site,
        app_settings=settings,
        registry=registry,
        run_overrides=run_overrides or {},
    )
    process.start()  # blocks until finished

    after = _pdf_count(settings, site.id)
    return {"total": after, "new": max(0, after - before)}


def _pdf_count(settings: Settings, site_id: int) -> int:
    with session(settings.db_path) as conn:
        return len(PdfRepository(conn).list_by_site(site_id))
