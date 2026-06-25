"""pdfscan MCP server (thin FastMCP adapter over :mod:`pdfscan.mcp.handlers`).

Exposes the full ScannerService surface -- sites, crawl/verify/pipeline, the
three-signal classifier, ownership/responsible-people tracking, exports
(including the HTML report), and maintenance -- as MCP tools so Claude Desktop
can drive the scanner. The handlers carry all logic, error-guarding, and
DB auto-migration; this module only wires them to FastMCP.

Run: ``pdfscan-mcp`` (stdio). Point it at the right database by launching it from
the project root, or set ``PDFSCAN_CONFIG`` / ``PDFSCAN_DB_PATH``.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from pdfscan.mcp import handlers

_INSTRUCTIONS = """\
pdfscan crawls websites for PDFs and verifies PDF/UA accessibility with veraPDF,
then classifies each PDF as good_to_go, fit_for_automated_tagging, or
needs_manual_remediation, and tracks who is responsible for each site.

Typical workflow:
  1. doctor() to confirm veraPDF/Java are available (setup_verapdf() if not).
  2. add_site(name, seeds) then crawl_site(name) then verify_site(name).
  3. site_status(name) for the triage summary; pdf_rules(name, url) to see why a
     PDF fails; export_results(name, "html") for a shareable report.
  4. Ownership: add_owner / add_person / assign_person / set_site_owner, then
     whois(name) to see responsible people (or import_people from CSVs).

crawl_site and run_pipeline are long-running and run in a subprocess. Every tool
returns a structured result and reports failures as {"error", "error_type"}
rather than raising. The database is migrated automatically on first use.
"""

mcp = FastMCP("pdfscan", instructions=_INSTRUCTIONS)

# Register every handler; FastMCP uses each function's name + docstring as the
# tool name + description.
for _handler in handlers.TOOLS:
    mcp.tool()(_handler)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
