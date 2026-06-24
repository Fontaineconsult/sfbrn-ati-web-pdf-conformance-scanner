"""The single generic, config-driven PDF discovery spider.

Replaces the original tool's 200+ generated per-domain spiders. Scope, depth,
JS-rendering, and which resolvers apply all come from the ``Site`` configuration
(plus per-run overrides) rather than being baked into generated code.
"""

from __future__ import annotations

from typing import Any

import scrapy

from pdfscan.config import Settings
from pdfscan.models import Site
from pdfscan.resolvers import ResolverRegistry, default_registry
from pdfscan.utils.urls import in_scope, is_pdf_url, normalize_url, seed_hosts_from

try:  # scrapy-playwright is optional at runtime (only needed for render_js sites)
    from scrapy_playwright.page import PageMethod
except Exception:  # pragma: no cover - import guard
    PageMethod = None  # type: ignore[assignment]


class GenericPdfSpider(scrapy.Spider):
    name = "pdf_generic"

    def __init__(
        self,
        site: Site,
        app_settings: Settings,
        registry: ResolverRegistry | None = None,
        run_overrides: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.site = site
        self.cfg = site.config
        self.app_settings = app_settings
        self.db_path = str(app_settings.db_path)
        ov = run_overrides or {}

        self.seed_hosts = seed_hosts_from(self.cfg)
        self.scope = self.cfg.scope
        self.path_prefix = self.cfg.path_prefix
        self.include_external_pdfs = bool(
            ov.get("include_external_pdfs", self.cfg.include_external_pdfs)
        )
        self.render_js = bool(
            ov.get("render_js")
            if ov.get("render_js") is not None
            else self.cfg.render_js
        )
        self.wait_until = app_settings.get("scrapy.playwright.wait_until", "networkidle")

        if registry is None:
            enabled = self.cfg.resolvers or app_settings.get("resolvers.enabled")
            registry = default_registry(enabled)
        self.registry = registry

    # -- requests ---------------------------------------------------------------
    def _seed_requests(self):
        for seed in self.cfg.seeds:
            yield self._page_request(seed, parent=seed)

    async def start(self):  # Scrapy >= 2.13 entry point
        for request in self._seed_requests():
            yield request

    def start_requests(self):  # backwards-compat for Scrapy < 2.13
        return self._seed_requests()

    def _page_meta(self) -> dict[str, Any]:
        meta: dict[str, Any] = {}
        if self.render_js and PageMethod is not None:
            meta["playwright"] = True
            meta["playwright_page_methods"] = [PageMethod("wait_for_load_state", self.wait_until)]
        return meta

    def _page_request(self, url: str, parent: str) -> scrapy.Request:
        return scrapy.Request(url, callback=self.parse, meta=self._page_meta(), dont_filter=False)

    def _url_in_scope(self, url: str) -> bool:
        return in_scope(
            url,
            scope=self.scope,
            seed_hosts=self.seed_hosts,
            path_prefix=self.path_prefix,
        )

    # -- parsing ----------------------------------------------------------------
    def parse(self, response):
        parent = response.url
        content_type = response.headers.get("Content-Type", b"").decode("latin-1", "ignore").lower()
        if "text/html" not in content_type and content_type:
            return  # don't try to extract links from non-HTML responses

        for href in response.css("a::attr(href)").getall():
            absolute = response.urljoin(href)
            if not absolute.lower().startswith(("http://", "https://")):
                continue
            url = normalize_url(absolute)

            if is_pdf_url(url):
                if self._url_in_scope(url):
                    yield self._pdf_item(url, parent, offsite=False)
                elif self.include_external_pdfs:
                    yield self._pdf_item(url, parent, offsite=True)
                continue

            resolver = self.registry.match(url)
            if resolver is not None:
                yield self._resolver_item(url, parent, resolver.name)
                continue

            if self._url_in_scope(url):
                yield response.follow(url, callback=self.parse, meta=self._page_meta())

    # -- items ------------------------------------------------------------------
    def _pdf_item(self, url: str, parent: str, offsite: bool):
        from pdfscan.scraper.items import PdfItem

        return PdfItem(
            pdf_url=url,
            parent_url=parent,
            needs_resolution=False,
            offsite=offsite,
            via_resolver=None,
            filename=None,
        )

    def _resolver_item(self, url: str, parent: str, resolver_name: str):
        from pdfscan.scraper.items import PdfItem

        return PdfItem(
            html_url=url,
            parent_url=parent,
            needs_resolution=True,
            offsite=not self._url_in_scope(url),
            via_resolver=resolver_name,
            filename=None,
        )
