"""SQLite connection factory + session context manager (WAL, row factory, FKs)."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def get_connection(
    db_path: str | os.PathLike,
    busy_timeout_ms: int = 30000,
    check_same_thread: bool = True,
) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(path), timeout=busy_timeout_ms / 1000, check_same_thread=check_same_thread
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def enable_wal(conn: sqlite3.Connection, busy_timeout_ms: int = 30000) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")


@contextmanager
def session(
    db_path: str | os.PathLike,
    wal: bool = True,
    busy_timeout_ms: int = 30000,
) -> Iterator[sqlite3.Connection]:
    """Open a connection, commit on success, roll back on error, always close."""
    conn = get_connection(db_path, busy_timeout_ms)
    if wal:
        enable_wal(conn, busy_timeout_ms)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
