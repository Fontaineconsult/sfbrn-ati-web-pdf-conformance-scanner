from __future__ import annotations

import sqlite3


class BaseRepository:
    """Repositories operate on a caller-provided connection so several can share a
    single transaction (the service layer owns the ``session()``)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
