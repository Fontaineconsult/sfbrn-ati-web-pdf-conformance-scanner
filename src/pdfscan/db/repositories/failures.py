from __future__ import annotations

from pdfscan.db.repositories.base import BaseRepository
from pdfscan.models import Failure


class FailureRepository(BaseRepository):
    def add(self, failure: Failure) -> int:
        cur = self.conn.execute(
            "INSERT INTO failure (site_id, pdf_id, error_message) VALUES (?, ?, ?)",
            (failure.site_id, failure.pdf_id, failure.error_message),
        )
        return int(cur.lastrowid)

    def list_by_site(self, site_id: int) -> list[Failure]:
        rows = self.conn.execute(
            "SELECT * FROM failure WHERE site_id = ? ORDER BY id", (site_id,)
        ).fetchall()
        return [
            Failure(
                id=r["id"],
                site_id=r["site_id"],
                pdf_id=r["pdf_id"],
                error_message=r["error_message"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def count_by_site(self, site_id: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM failure WHERE site_id = ?", (site_id,)
        ).fetchone()
        return int(row[0])
