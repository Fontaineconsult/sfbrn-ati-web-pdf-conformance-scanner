"""Item pipeline: resolve special-case links, dedup, and persist PDF rows.

The plan describes three stages (resolve -> dedup -> persist); they are combined
into one cohesive pipeline because resolution can fan a single resolver link into
multiple concrete PDFs, which is awkward to express as item-out stages. Each
concern stays in its own private method.
"""

from __future__ import annotations

from scrapy.exceptions import DropItem

from pdfscan.db.engine import enable_wal, get_connection
from pdfscan.db.repositories import FailureRepository, PdfRepository
from pdfscan.models import DiscoveredPdf, Failure


class PdfPipeline:
    def open_spider(self, spider) -> None:
        self.conn = get_connection(spider.db_path, check_same_thread=False)
        enable_wal(self.conn)
        self.pdfs = PdfRepository(self.conn)
        self.failures = FailureRepository(self.conn)
        self.registry = spider.registry
        self.site_id = spider.site.id
        self.seen: set[tuple[str, str]] = set()
        self.persisted = 0
        self.resolved = 0
        self.unresolved = 0

    def close_spider(self, spider) -> None:
        try:
            self.conn.commit()
        finally:
            self.conn.close()
        spider.logger.info(
            "pdfscan: persisted=%d resolved=%d unresolved=%d",
            self.persisted,
            self.resolved,
            self.unresolved,
        )

    def process_item(self, item, spider):
        parent = item["parent_url"]
        via = item.get("via_resolver")
        offsite = bool(item.get("offsite"))

        if item.get("needs_resolution"):
            urls = self._resolve(item, spider)
        else:
            urls = [item["pdf_url"]]

        for url in urls:
            key = (url, parent)
            if key in self.seen:
                continue
            self.seen.add(key)
            try:
                self.pdfs.upsert(
                    DiscoveredPdf(
                        pdf_url=url,
                        parent_url=parent,
                        site_id=self.site_id,
                        via_resolver=via,
                        offsite=offsite,
                    )
                )
                self.persisted += 1
            except Exception as exc:  # pragma: no cover - defensive
                spider.logger.warning("pdfscan: persist failed for %s: %s", url, exc)

        self.conn.commit()
        return item

    # -- helpers ----------------------------------------------------------------
    def _resolve(self, item, spider) -> list[str]:
        html_url = item["html_url"]
        result = self.registry.resolve(html_url)
        if result.error or not result.pdf_urls:
            self.unresolved += 1
            self.failures.add(
                Failure(
                    site_id=self.site_id,
                    pdf_id=None,
                    error_message=f"resolve {html_url}: {result.error or 'no pdf urls'}",
                )
            )
            self.conn.commit()
            raise DropItem(f"unresolved: {html_url}")
        self.resolved += 1
        return list(result.pdf_urls)
