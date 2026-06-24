"""Stream a PDF URL to a local file, with a size cap and SSL-retry fallback."""

from __future__ import annotations

import os
from pathlib import Path

import requests
import urllib3

from pdfscan.utils.http import build_session


class DownloadError(Exception):
    pass


def download_to_file(
    url: str,
    dest: str | os.PathLike,
    *,
    timeout: int = 30,
    max_bytes: int | None = None,
    ssl_insecure_retry: bool = True,
    session: requests.Session | None = None,
) -> Path:
    """Download ``url`` to ``dest`` (streamed). Raises DownloadError on size cap,
    or requests exceptions on network/HTTP failure. Mirrors the original tool's
    verify=True -> verify=False SSL retry."""
    dest = Path(dest)
    sess = session or build_session()

    def _attempt(verify: bool) -> int:
        with sess.get(url, stream=True, timeout=timeout, verify=verify) as resp:
            resp.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            total = 0
            with open(dest, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if max_bytes and total > max_bytes:
                        raise DownloadError(f"PDF exceeds max_bytes ({max_bytes})")
                    fh.write(chunk)
            return total

    try:
        _attempt(verify=True)
    except requests.exceptions.SSLError:
        if not ssl_insecure_retry:
            raise
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        _attempt(verify=False)
    return dest
