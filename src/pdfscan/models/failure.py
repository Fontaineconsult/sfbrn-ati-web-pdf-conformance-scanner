from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Failure:
    """A persisted ``failure`` row (download/resolve/verify error)."""

    site_id: int | None
    pdf_id: int | None
    error_message: str
    id: int | None = None
    created_at: str | None = None
