"""Compute where a downloaded PDF should be saved for remediation.

Default template (from settings ``storage.template``) mirrors the site's URL
path so a saved PDF is traceable back to its page:
    {root}/{site}/{path}/{filename}
Tokens: {root} {site} {path} {filename} {hash} {date}. Path segments are
URL-decoded and sanitized for the filesystem (Windows-safe).
"""

from __future__ import annotations

import datetime
import re
import shutil
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _sanitize(part: str) -> str:
    part = unquote(part)
    part = _ILLEGAL.sub("_", part).strip().strip(".")
    return part[:150]


def _url_parts(pdf_url: str, file_hash: str) -> tuple[str, str]:
    parsed = urlparse(pdf_url)
    path = PurePosixPath(parsed.path)
    filename = _sanitize(path.name) if path.name else ""
    if not filename or not filename.lower().endswith(".pdf"):
        filename = f"{file_hash[:16]}.pdf" if file_hash else "document.pdf"
    sub_segments = [_sanitize(s) for s in path.parts[1:-1]] if len(path.parts) > 1 else []
    sub = "/".join(s for s in sub_segments if s)
    return sub, filename


def render_storage_path(
    pdf_url: str,
    site_name: str,
    file_hash: str,
    *,
    root: str | Path,
    template: str,
    today: str | None = None,
) -> Path:
    sub, filename = _url_parts(pdf_url, file_hash)
    rendered = template.format(
        root=str(root),
        site=_sanitize(site_name),
        path=sub,
        filename=filename,
        hash=file_hash or "nohash",
        date=today or datetime.date.today().isoformat(),
    )
    # Path() collapses any doubled separators left by an empty {path} token.
    return Path(rendered)


def save_pdf(
    temp_path: str | Path,
    pdf_url: str,
    site_name: str,
    file_hash: str,
    *,
    root: str | Path,
    template: str,
) -> Path:
    """Copy a downloaded temp PDF into its remediation location. Returns the dest."""
    dest = render_storage_path(pdf_url, site_name, file_hash, root=root, template=template)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(temp_path, dest)
    return dest
