from __future__ import annotations

import pytest

from pdfscan.db.engine import get_connection
from pdfscan.db.schema import create_all
from pdfscan.models import Site, SiteConfig


@pytest.fixture(autouse=True)
def _isolate_sessions(tmp_path, monkeypatch):
    """Point the session registry at a throwaway file so tests never read (or
    write) the real user-level ``sessions.yaml``. The file does not exist, so the
    registry loads empty unless a test creates it."""
    monkeypatch.setenv("PDFSCAN_SESSIONS_FILE", str(tmp_path / "sessions.yaml"))


@pytest.fixture
def conn(tmp_path):
    db = tmp_path / "test.db"
    c = get_connection(db)
    create_all(c)
    c.commit()
    try:
        yield c
    finally:
        c.close()


@pytest.fixture
def sample_site() -> Site:
    return Site(
        id=None,
        name="hr",
        config=SiteConfig(seeds=["https://hr.sfsu.edu"], scope="host", max_depth=3),
    )
