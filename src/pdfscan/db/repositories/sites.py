from __future__ import annotations

import sqlite3

from pdfscan.db.repositories.base import BaseRepository
from pdfscan.models import Site, SiteConfig


def _row_to_site(row: sqlite3.Row) -> Site:
    return Site(
        id=row["id"],
        name=row["name"],
        config=SiteConfig.from_json(row["config_json"]),
        enabled=bool(row["enabled"]),
        notes=row["notes"],
        created_at=row["created_at"],
    )


class SiteRepository(BaseRepository):
    def add(self, site: Site) -> int:
        cur = self.conn.execute(
            "INSERT INTO site (name, config_json, enabled, notes) VALUES (?, ?, ?, ?)",
            (site.name, site.config.to_json(), int(site.enabled), site.notes),
        )
        return int(cur.lastrowid)

    def upsert(self, site: Site) -> int:
        """Insert, or replace config/notes/enabled if the name already exists."""
        cur = self.conn.execute(
            """
            INSERT INTO site (name, config_json, enabled, notes)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                config_json = excluded.config_json,
                enabled = excluded.enabled,
                notes = excluded.notes
            RETURNING id
            """,
            (site.name, site.config.to_json(), int(site.enabled), site.notes),
        )
        return int(cur.fetchone()[0])

    def get_by_id(self, site_id: int) -> Site | None:
        row = self.conn.execute("SELECT * FROM site WHERE id = ?", (site_id,)).fetchone()
        return _row_to_site(row) if row else None

    def get_by_name(self, name: str) -> Site | None:
        row = self.conn.execute("SELECT * FROM site WHERE name = ?", (name,)).fetchone()
        return _row_to_site(row) if row else None

    def list(self, enabled_only: bool = False) -> list[Site]:
        sql = "SELECT * FROM site"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY name"
        return [_row_to_site(r) for r in self.conn.execute(sql).fetchall()]

    def remove(self, name: str) -> bool:
        cur = self.conn.execute("DELETE FROM site WHERE name = ?", (name,))
        return cur.rowcount > 0
