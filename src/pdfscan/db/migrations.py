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
    # v2 adds the report_rule table; it is created by create_all() above
    # (CREATE TABLE IF NOT EXISTS), so only the version stamp needs bumping.
    # Future column changes add explicit `if version < N:` ALTER blocks here.
    if version != SCHEMA_VERSION:
        conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))
        version = SCHEMA_VERSION
    return version
