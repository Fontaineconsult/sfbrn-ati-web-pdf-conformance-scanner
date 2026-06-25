from __future__ import annotations

import sqlite3

from pdfscan.db.repositories.base import BaseRepository
from pdfscan.models import DiscoveredPdf, PdfFile


def _row_to_pdf(row: sqlite3.Row) -> PdfFile:
    return PdfFile(
        id=row["id"],
        pdf_url=row["pdf_url"],
        parent_url=row["parent_url"],
        site_id=row["site_id"],
        file_hash=row["file_hash"],
        via_resolver=row["via_resolver"],
        offsite=bool(row["offsite"]),
        local_path=row["local_path"],
        scanned_at=row["scanned_at"],
        pdf_404=bool(row["pdf_404"]),
        parent_404=bool(row["parent_404"]),
        archived=bool(row["archived"]),
        removed=bool(row["removed"]),
    )


class PdfRepository(BaseRepository):
    def upsert(self, pdf: DiscoveredPdf) -> int:
        """Insert a discovered PDF (file_hash filled later by verify). Dedup on
        (pdf_url, parent_url); re-discovery refreshes scanned_at and clears removed."""
        cur = self.conn.execute(
            """
            INSERT INTO pdf_files (pdf_url, parent_url, site_id, via_resolver, offsite)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(pdf_url, parent_url) DO UPDATE SET
                scanned_at = CURRENT_TIMESTAMP,
                via_resolver = excluded.via_resolver,
                offsite = excluded.offsite,
                removed = 0
            RETURNING id
            """,
            (pdf.pdf_url, pdf.parent_url, pdf.site_id, pdf.via_resolver, int(pdf.offsite)),
        )
        return int(cur.fetchone()[0])

    def exists(self, pdf_url: str, parent_url: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM pdf_files WHERE pdf_url = ? AND parent_url = ?",
            (pdf_url, parent_url),
        ).fetchone()
        return row is not None

    def get(self, pdf_id: int) -> PdfFile | None:
        row = self.conn.execute("SELECT * FROM pdf_files WHERE id = ?", (pdf_id,)).fetchone()
        return _row_to_pdf(row) if row else None

    def list_by_site(self, site_id: int, include_removed: bool = False) -> list[PdfFile]:
        sql = "SELECT * FROM pdf_files WHERE site_id = ?"
        if not include_removed:
            sql += " AND removed = 0"
        sql += " ORDER BY id"
        return [_row_to_pdf(r) for r in self.conn.execute(sql, (site_id,)).fetchall()]

    def list_unverified(self, site_id: int) -> list[PdfFile]:
        """Rows lacking a stored report (no hash, or hash with no pdf_report row).

        Known-404 PDFs are skipped -- there is nothing to download, so re-running
        verify should not keep retrying them. Clearing the flag (e.g. via
        ``check-404`` after the file returns) makes them eligible again.
        """
        rows = self.conn.execute(
            """
            SELECT f.* FROM pdf_files f
            LEFT JOIN pdf_report r ON r.pdf_hash = f.file_hash
            WHERE f.site_id = ? AND f.removed = 0 AND f.pdf_404 = 0
              AND (f.file_hash IS NULL OR r.id IS NULL)
            ORDER BY f.id
            """,
            (site_id,),
        ).fetchall()
        return [_row_to_pdf(r) for r in rows]

    def set_verified(self, pdf_id: int, file_hash: str, local_path: str | None) -> None:
        self.conn.execute(
            "UPDATE pdf_files SET file_hash = ?, local_path = ? WHERE id = ?",
            (file_hash, local_path, pdf_id),
        )

    def set_404(self, pdf_id: int, pdf_404: bool, parent_404: bool) -> None:
        self.conn.execute(
            "UPDATE pdf_files SET pdf_404 = ?, parent_404 = ? WHERE id = ?",
            (int(pdf_404), int(parent_404), pdf_id),
        )

    def set_archived(self, pdf_id: int, archived: bool) -> None:
        self.conn.execute(
            "UPDATE pdf_files SET archived = ? WHERE id = ?", (int(archived), pdf_id)
        )

    def set_removed(self, pdf_id: int, removed: bool) -> None:
        self.conn.execute(
            "UPDATE pdf_files SET removed = ? WHERE id = ?", (int(removed), pdf_id)
        )

    def export_rows(self, site_id: int | None = None) -> list[dict]:
        """Flat join of pdf_files + pdf_report + site for exporters/queries."""
        sql = """
            SELECT s.name AS site, f.pdf_url, f.parent_url, f.scanned_at, f.offsite,
                   f.via_resolver, f.local_path, f.archived, f.removed,
                   f.pdf_404, f.parent_404, f.file_hash,
                   r.violations, r.failed_checks, r.tagged, r.image_only,
                   r.text_type, r.title_set, r.language_set, r.page_count, r.has_form,
                   r.complex_graphic,
                   o.key AS owner,
                   (SELECT group_concat(p.email, '; ')
                      FROM person p
                      JOIN person_owner po ON po.person_id = p.id
                     WHERE po.owner_id = s.owner_id) AS responsible
            FROM pdf_files f
            JOIN site s ON s.id = f.site_id
            LEFT JOIN site_owner o ON o.id = s.owner_id
            LEFT JOIN pdf_report r ON r.pdf_hash = f.file_hash
        """
        params: tuple = ()
        if site_id is not None:
            sql += " WHERE f.site_id = ?"
            params = (site_id,)
        sql += " ORDER BY s.name, f.pdf_url"
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]
