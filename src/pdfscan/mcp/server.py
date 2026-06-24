"""pdfscan MCP server.

Exposes the ScannerService as MCP tools so Claude Desktop can drive scans.
Crawling and the full pipeline run in a subprocess (Scrapy installs a Twisted
reactor that must not share the MCP server's asyncio loop); everything else
calls the service facade directly.

Run: ``pdfscan-mcp`` (stdio). Configure the working directory to the project
root, or set PDFSCAN_CONFIG / PDFSCAN_DB_PATH so the right DB/config is used.
"""

from __future__ import annotations

import subprocess
import sys

from mcp.server.fastmcp import FastMCP

from pdfscan.service import ScannerService
from pdfscan.service.facade import ScannerError

mcp = FastMCP("pdfscan")


def _svc() -> ScannerService:
    return ScannerService()


def _cli(*args: str) -> dict:
    """Invoke the pdfscan CLI in a subprocess (used for reactor-bound commands)."""
    proc = subprocess.run(
        [sys.executable, "-m", "pdfscan", *args],
        capture_output=True,
        text=True,
    )
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-1500:],
    }


@mcp.tool()
def list_sites() -> list[dict]:
    """List configured sites with PDF counts."""
    return _svc().list_sites()


@mcp.tool()
def add_site(
    name: str,
    seeds: list[str],
    scope: str = "host",
    depth: int = 0,
    render_js: bool = False,
    include_external_pdfs: bool = False,
) -> dict:
    """Add or update a site to scan. scope = host|subdomain|domain|path."""
    try:
        sid = _svc().add_site(
            name, seeds, scope=scope, depth=depth,
            render_js=render_js, include_external_pdfs=include_external_pdfs,
        )
    except ScannerError as exc:
        return {"error": str(exc)}
    return {"id": sid, "name": name}


@mcp.tool()
def crawl_site(name: str, max_pages: int | None = None, depth: int | None = None) -> dict:
    """Crawl a site for PDFs (runs in a subprocess)."""
    args = ["crawl", name]
    if max_pages is not None:
        args += ["--max-pages", str(max_pages)]
    if depth is not None:
        args += ["--depth", str(depth)]
    return _cli(*args)


@mcp.tool()
def verify_site(name: str, limit: int | None = None) -> dict:
    """Download + veraPDF-verify a site's PDFs. Returns counts."""
    try:
        return _svc().verify(name, limit=limit)
    except ScannerError as exc:
        return {"error": str(exc)}


@mcp.tool()
def run_pipeline(name: str, limit: int | None = None, export: list[str] | None = None) -> dict:
    """Full pipeline (crawl + verify + archive + export) in a subprocess."""
    args = ["run", name]
    if limit is not None:
        args += ["--limit", str(limit)]
    for fmt in export or []:
        args += ["--export", fmt]
    return _cli(*args)


@mcp.tool()
def site_status(name: str) -> dict:
    """Coverage + accessibility summary for a site."""
    try:
        return _svc().status(name)
    except ScannerError as exc:
        return {"error": str(exc)}


@mcp.tool()
def export_results(name: str, fmt: str = "json", out: str = "exports/export.json") -> dict:
    """Export a site's results to csv/json/excel."""
    try:
        return _svc().export(fmt, out, name=name)
    except ScannerError as exc:
        return {"error": str(exc)}


@mcp.tool()
def test_archive_rule(urls: list[str]) -> list[dict]:
    """Dry-run the archive heuristics against URLs (no scan)."""
    return _svc().test_archive_rule(urls)


@mcp.tool()
def doctor() -> dict:
    """Report Java / veraPDF / Playwright availability."""
    return _svc().doctor()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
