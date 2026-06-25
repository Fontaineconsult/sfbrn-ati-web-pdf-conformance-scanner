"""Generalized SQLite schema (DDL) and table creation."""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 2

DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS site (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    config_json TEXT NOT NULL,
    enabled     INTEGER NOT NULL DEFAULT 1,
    notes       TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pdf_files (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    pdf_url      TEXT NOT NULL,
    parent_url   TEXT NOT NULL,
    site_id      INTEGER NOT NULL,
    file_hash    TEXT,
    via_resolver TEXT,
    offsite      INTEGER NOT NULL DEFAULT 0,
    local_path   TEXT,
    scanned_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    pdf_404      INTEGER NOT NULL DEFAULT 0,
    parent_404   INTEGER NOT NULL DEFAULT 0,
    archived     INTEGER NOT NULL DEFAULT 0,
    removed      INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (site_id) REFERENCES site(id) ON DELETE CASCADE,
    UNIQUE (pdf_url, parent_url)
);
CREATE INDEX IF NOT EXISTS ix_pdf_files_site ON pdf_files(site_id);
CREATE INDEX IF NOT EXISTS ix_pdf_files_hash ON pdf_files(file_hash);

CREATE TABLE IF NOT EXISTS pdf_report (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    pdf_hash      TEXT NOT NULL UNIQUE,
    violations    INTEGER NOT NULL DEFAULT 0,
    failed_checks INTEGER NOT NULL DEFAULT 0,
    tagged        INTEGER NOT NULL DEFAULT 0,
    image_only    INTEGER NOT NULL DEFAULT 0,
    text_type     TEXT,
    title_set     INTEGER NOT NULL DEFAULT 0,
    language_set  INTEGER NOT NULL DEFAULT 0,
    page_count    INTEGER,
    has_form      INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Per-rule veraPDF results, stored verbatim (no ignore policy applied) so the
-- ignore profile can be re-evaluated without re-running veraPDF. One row per
-- failing clause/test; aggregates in pdf_report are derivable from these.
CREATE TABLE IF NOT EXISTS report_rule (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    pdf_hash      TEXT NOT NULL,
    clause        TEXT,
    test_number   TEXT,
    status        TEXT,
    failed_checks INTEGER NOT NULL DEFAULT 0,
    specification TEXT,
    description   TEXT,
    FOREIGN KEY (pdf_hash) REFERENCES pdf_report(pdf_hash) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_report_rule_hash ON report_rule(pdf_hash);

CREATE TABLE IF NOT EXISTS failure (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id       INTEGER,
    pdf_id        INTEGER,
    error_message TEXT NOT NULL,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (site_id) REFERENCES site(id) ON DELETE SET NULL,
    FOREIGN KEY (pdf_id) REFERENCES pdf_files(id) ON DELETE SET NULL
);
"""


def create_all(conn: sqlite3.Connection) -> None:
    """Create all tables and stamp the schema version (idempotent)."""
    conn.executescript(DDL)
    row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
