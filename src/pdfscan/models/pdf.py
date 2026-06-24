from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DiscoveredPdf:
    """A PDF link found during a crawl, before download/verification."""

    pdf_url: str
    parent_url: str
    site_id: int
    via_resolver: str | None = None
    offsite: bool = False
    filename: str | None = None


@dataclass
class PdfFile:
    """A persisted ``pdf_files`` row."""

    id: int | None
    pdf_url: str
    parent_url: str
    site_id: int
    file_hash: str | None = None
    via_resolver: str | None = None
    offsite: bool = False
    local_path: str | None = None
    scanned_at: str | None = None
    pdf_404: bool = False
    parent_404: bool = False
    archived: bool = False
    removed: bool = False
