from __future__ import annotations

from pdfscan.db.engine import get_connection
from pdfscan.db.migrations import migrate

# pdf_report DDL as it existed at schema v2 (no complex_graphic column).
_V2_PDF_REPORT = """
CREATE TABLE schema_version (version INTEGER NOT NULL);
CREATE TABLE pdf_report (
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
"""


def _columns(conn, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def test_migrate_v2_to_v3_adds_complex_graphic(tmp_path):
    conn = get_connection(tmp_path / "v2.db")
    conn.executescript(_V2_PDF_REPORT)
    conn.execute("INSERT INTO schema_version (version) VALUES (2)")
    conn.commit()
    assert "complex_graphic" not in _columns(conn, "pdf_report")

    version = migrate(conn)

    assert version == 4  # migrating an old DB brings it to the current schema
    assert "complex_graphic" in _columns(conn, "pdf_report")
    conn.close()


def test_migrate_fresh_db_is_v3_and_idempotent(tmp_path):
    conn = get_connection(tmp_path / "fresh.db")
    assert migrate(conn) == 4
    assert "complex_graphic" in _columns(conn, "pdf_report")
    # Re-running migrate must not error or duplicate the column.
    assert migrate(conn) == 4
    assert _columns(conn, "pdf_report").count("complex_graphic") == 1
    conn.close()


# A v3 ``site`` table (no owner_id column, no ownership tables yet).
_V3_SITE = """
CREATE TABLE schema_version (version INTEGER NOT NULL);
CREATE TABLE site (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    config_json TEXT NOT NULL,
    enabled     INTEGER NOT NULL DEFAULT 1,
    notes       TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def test_migrate_v3_to_v4_adds_owner_id_and_tables(tmp_path):
    conn = get_connection(tmp_path / "v3.db")
    conn.executescript(_V3_SITE)
    conn.execute("INSERT INTO schema_version (version) VALUES (3)")
    conn.commit()
    assert "owner_id" not in _columns(conn, "site")

    version = migrate(conn)

    assert version == 4
    assert "owner_id" in _columns(conn, "site")
    # the three ownership tables now exist (PRAGMA returns columns for real tables)
    assert _columns(conn, "site_owner")
    assert _columns(conn, "person")
    assert _columns(conn, "person_owner")
    conn.close()


def test_migrate_fresh_db_is_v4_and_idempotent(tmp_path):
    conn = get_connection(tmp_path / "fresh4.db")
    assert migrate(conn) == 4
    assert "owner_id" in _columns(conn, "site")
    # Re-running migrate must not error or duplicate the column.
    assert migrate(conn) == 4
    assert _columns(conn, "site").count("owner_id") == 1
    conn.close()
