"""Build a Scrapy settings dict for a single site crawl.

Merge order (lowest -> highest): global settings.yaml defaults < per-site
SiteConfig < per-run overrides (CLI flags). Playwright handlers are only wired
in when the site/run requests JS rendering, so static crawls stay lightweight.
"""

from __future__ import annotations

from typing import Any

from pdfscan.config import Settings
from pdfscan.models import Site

PLAYWRIGHT_HANDLER = "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler"


def _pick(override, site_val, default):
    if override is not None:
        return override
    if site_val is not None:
        return site_val
    return default


def build_scrapy_settings(
    site: Site,
    settings: Settings,
    run_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = site.config
    ov = run_overrides or {}

    delay = _pick(ov.get("download_delay"), cfg.download_delay, settings.get("scrapy.download_delay", 0.5))
    concurrency = _pick(
        ov.get("concurrency"), cfg.concurrency, settings.get("scrapy.concurrent_requests_per_domain", 4)
    )
    obey = _pick(ov.get("obey_robots"), cfg.obey_robots, settings.get("scrapy.obey_robots", False))
    depth = _pick(ov.get("max_depth"), cfg.max_depth, settings.get("crawl.max_depth", 0))

    scrapy_settings: dict[str, Any] = {
        "BOT_NAME": "pdfscan",
        "USER_AGENT": settings.get("scrapy.user_agent", "pdfscan/0.1"),
        "ROBOTSTXT_OBEY": bool(obey),
        "DOWNLOAD_DELAY": float(delay),
        "CONCURRENT_REQUESTS": int(settings.get("scrapy.concurrent_requests", 16)),
        "CONCURRENT_REQUESTS_PER_DOMAIN": int(concurrency),
        "DEPTH_LIMIT": int(depth),  # 0 == unlimited (matches our config convention)
        "AUTOTHROTTLE_ENABLED": bool(settings.get("scrapy.autothrottle.enabled", True)),
        "AUTOTHROTTLE_START_DELAY": settings.get("scrapy.autothrottle.start_delay", 5),
        "AUTOTHROTTLE_MAX_DELAY": settings.get("scrapy.autothrottle.max_delay", 60),
        "AUTOTHROTTLE_TARGET_CONCURRENCY": settings.get("scrapy.autothrottle.target_concurrency", 1.0),
        "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
        "TELNETCONSOLE_ENABLED": False,
        "LOG_LEVEL": ov.get("log_level", "INFO"),
        "ITEM_PIPELINES": {"pdfscan.scraper.pipelines.PdfPipeline": 300},
        "DEPTH_PRIORITY": 1,  # breadth-first: discover shallow pages first
        "SCHEDULER_DISK_QUEUE": "scrapy.squeues.PickleFifoDiskQueue",
        "SCHEDULER_MEMORY_QUEUE": "scrapy.squeues.FifoMemoryQueue",
    }

    # Optional safety caps for bounded test crawls.
    if ov.get("max_pages"):
        scrapy_settings["CLOSESPIDER_PAGECOUNT"] = int(ov["max_pages"])
    if ov.get("timeout_s"):
        scrapy_settings["CLOSESPIDER_TIMEOUT"] = int(ov["timeout_s"])

    render_js = _pick(ov.get("render_js"), cfg.render_js, settings.get("scrapy.playwright.enabled_default", False))
    if render_js:
        scrapy_settings["DOWNLOAD_HANDLERS"] = {"http": PLAYWRIGHT_HANDLER, "https": PLAYWRIGHT_HANDLER}
        scrapy_settings["PLAYWRIGHT_BROWSER_TYPE"] = settings.get("scrapy.playwright.browser", "chromium")
        scrapy_settings["PLAYWRIGHT_LAUNCH_OPTIONS"] = {
            "headless": bool(settings.get("scrapy.playwright.headless", True))
        }
        scrapy_settings["PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT"] = int(
            settings.get("scrapy.playwright.timeout_ms", 30000)
        )

    return scrapy_settings
