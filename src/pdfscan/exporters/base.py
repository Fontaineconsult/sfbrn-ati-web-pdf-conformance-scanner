"""Shared row collection for exporters."""

from __future__ import annotations

from pdfscan.config import Settings
from pdfscan.db import session
from pdfscan.db.repositories import PdfRepository, SiteRepository

# Stable column order for tabular exports.
COLUMNS = [
    "site",
    "pdf_url",
    "parent_url",
    "scanned_at",
    "offsite",
    "via_resolver",
    "archived",
    "removed",
    "pdf_404",
    "parent_404",
    "file_hash",
    "violations",
    "failed_checks",
    "tagged",
    "image_only",
    "text_type",
    "title_set",
    "language_set",
    "page_count",
    "has_form",
    "local_path",
]


def collect_rows(settings: Settings, site_name: str | None = None) -> list[dict]:
    """Return flat joined rows (pdf_files + pdf_report) for a site or all sites."""
    with session(settings.db_path) as conn:
        site_id = None
        if site_name:
            site = SiteRepository(conn).get_by_name(site_name)
            if site is None:
                raise ValueError(f"No such site '{site_name}'")
            site_id = site.id
        rows = PdfRepository(conn).export_rows(site_id)
    # normalize to a stable column set/order
    return [{col: row.get(col) for col in COLUMNS} for row in rows]
