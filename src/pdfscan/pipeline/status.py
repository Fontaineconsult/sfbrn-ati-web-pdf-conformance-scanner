"""Refresh 404 status for discovered PDFs and their parent pages."""

from __future__ import annotations

import sqlite3

from pdfscan.config import Settings
from pdfscan.db.repositories import PdfRepository
from pdfscan.utils.http import build_session, head_status


def refresh_404(conn: sqlite3.Connection, site_id: int, settings: Settings) -> dict[str, int]:
    pdfs = PdfRepository(conn)
    sess = build_session(settings.get("scrapy.user_agent", "pdfscan/0.1"))
    timeout = int(settings.get("download.timeout", 30))

    stats = {"checked": 0, "pdf_404": 0, "parent_404": 0}
    parent_cache: dict[str, int | None] = {}
    for pdf in pdfs.list_by_site(site_id):
        pdf_status = head_status(pdf.pdf_url, timeout=timeout, session=sess)
        if pdf.parent_url not in parent_cache:
            parent_cache[pdf.parent_url] = head_status(pdf.parent_url, timeout=timeout, session=sess)
        parent_status = parent_cache[pdf.parent_url]

        pdf_404 = pdf_status == 404
        parent_404 = parent_status == 404
        pdfs.set_404(pdf.id, pdf_404, parent_404)
        stats["checked"] += 1
        stats["pdf_404"] += int(pdf_404)
        stats["parent_404"] += int(parent_404)
    return stats
