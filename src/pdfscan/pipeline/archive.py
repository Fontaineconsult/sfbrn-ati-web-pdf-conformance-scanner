"""Heuristics for flagging PDFs as 'archived' (URL/path/filename based).

Rules are config-driven (settings ``archive`` section). ``explain`` powers the
``pdfscan archive test`` starter tool so rules can be tuned without a full scan.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse

from pdfscan.config import Settings
from pdfscan.db.repositories import PdfRepository


@dataclass(frozen=True)
class ArchiveRules:
    keywords: list[str]
    path_segments: list[str]
    filename_prefixes: list[str]
    filename_suffixes: list[str]


def rules_from_settings(settings: Settings) -> ArchiveRules:
    return ArchiveRules(
        keywords=[k.lower() for k in settings.get("archive.keywords", [])],
        path_segments=[s.lower() for s in settings.get("archive.path_segments", [])],
        filename_prefixes=[p.lower() for p in settings.get("archive.filename_prefixes", [])],
        filename_suffixes=[s.lower() for s in settings.get("archive.filename_suffixes", [])],
    )


def explain(url: str, rules: ArchiveRules) -> str | None:
    """Return a human reason if the URL looks archived, else None."""
    lower = unquote(url).lower()
    path = urlparse(lower).path
    filename = PurePosixPath(path).name
    stem = filename[:-4] if filename.endswith(".pdf") else filename

    for seg in rules.path_segments:
        if seg in path:
            return f"path segment '{seg}'"
    for pre in rules.filename_prefixes:
        if filename.startswith(pre):
            return f"filename prefix '{pre}'"
    for suf in rules.filename_suffixes:
        if stem.endswith(suf):
            return f"filename suffix '{suf}'"
    for kw in rules.keywords:
        if kw in lower:
            return f"keyword '{kw}'"
    return None


def is_archived(url: str, rules: ArchiveRules) -> bool:
    return explain(url, rules) is not None


def apply_archive_flags(conn: sqlite3.Connection, site_id: int, rules: ArchiveRules) -> int:
    """Flag matching PDFs as archived. Returns the number newly/again flagged."""
    pdfs = PdfRepository(conn)
    flagged = 0
    for pdf in pdfs.list_by_site(site_id):
        if is_archived(pdf.pdf_url, rules):
            pdfs.set_archived(pdf.id, True)
            flagged += 1
    return flagged
