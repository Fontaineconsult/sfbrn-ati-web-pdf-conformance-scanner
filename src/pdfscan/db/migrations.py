"""Versioned migration runner. v1 is the initial schema (see schema.py)."""

from __future__ import annotations

import sqlite3

from pdfscan.db.schema import SCHEMA_VERSION, create_all


def current_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row[0]) if row else 0


def migrate(conn: sqlite3.Connection) -> int:
    """Bring the database up to SCHEMA_VERSION. Returns the resulting version.

    Future schema changes add ``if version < N:`` blocks here that ALTER tables
    and bump schema_version.
    """
    create_all(conn)
    version = current_version(conn)
    # v2 adds the report_rule table (created by create_all() above).
    # v3 adds pdf_report.complex_graphic. create_all() handles fresh DBs; an
    # existing pdf_report needs an explicit ALTER (idempotent via PRAGMA check).
    if version < 3:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(pdf_report)")]
        if "complex_graphic" not in cols:
            conn.execute(
                "ALTER TABLE pdf_report ADD COLUMN complex_graphic INTEGER NOT NULL DEFAULT 0"
            )
    # v4 adds ownership: site_owner / person / person_owner (created by create_all
    # above) and a site.owner_id FK column. Existing site tables need the explicit
    # ALTER; fresh DBs get owner_id (with the ON DELETE SET NULL action) from the DDL.
    if version < 4:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(site)")]
        if "owner_id" not in cols:
            conn.execute(
                "ALTER TABLE site ADD COLUMN owner_id INTEGER "
                "REFERENCES site_owner(id) ON DELETE SET NULL"
            )
    if version != SCHEMA_VERSION:
        conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))
        version = SCHEMA_VERSION
    return version
