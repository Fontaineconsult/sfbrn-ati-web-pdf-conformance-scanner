# pdfscan — Generalized PDF Accessibility Scanner

Crawl any website (scoped to a host/subdomain) for PDFs, save them for
remediation, and verify accessibility (PDF/UA) with a bundled **veraPDF**.

A generalized rebuild of the SF State PDF website scanner: one config-driven
Scrapy spider (no per-site spider generation), pluggable special-case resolvers
(Box.com first), scrapy-playwright for JS-rendered sites, SQLite persistence,
and CLI / CSV-Excel-JSON outputs. Architected so the same core can be driven
from a Claude Desktop MCP server or Skill.

## Status

Under active construction — see `M*` milestones in the build plan.

## Requirements

- Python >= 3.12 (developed on 3.14)
- Java 8+ on PATH (for veraPDF)
- Internet access on first run (to download veraPDF and the Chromium browser)

## Install (development)

```powershell
# from the repo root, with the project venv active
python -m pip install -e ".[dev]"
python -m playwright install chromium
pdfscan setup-verapdf      # downloads the bundled veraPDF (needs Java + network)
pdfscan doctor             # verify Java / veraPDF / Chromium
```

## Quickstart

```powershell
pdfscan db init
pdfscan site add hr --seed https://hr.sfsu.edu --scope host --depth 3
pdfscan crawl hr           # discover PDFs
pdfscan verify hr          # download + veraPDF + analyze, save copies for remediation
pdfscan export excel hr --out hr.xlsx
```

## Claude Desktop (MCP) & Skill

The same operations are exposed to Claude.

**MCP server** (`pdfscan-mcp`, stdio). Add to your Claude Desktop config:
```json
{
  "mcpServers": {
    "pdfscan": {
      "command": "C:\\path\\to\\sfbrn-pdf-scanner\\.venv\\Scripts\\pdfscan-mcp.exe",
      "env": {
        "PDFSCAN_CONFIG": "C:\\path\\to\\sfbrn-pdf-scanner\\config\\settings.yaml",
        "PDFSCAN_DB_PATH": "C:\\path\\to\\sfbrn-pdf-scanner\\data\\pdfscan.db"
      }
    }
  }
}
```
Tools: `list_sites`, `add_site`, `crawl_site`, `verify_site`, `run_pipeline`,
`site_status`, `export_results`, `test_archive_rule`, `doctor`. (`crawl_site` and
`run_pipeline` shell out to the CLI so Scrapy's reactor never clashes with the
MCP event loop.)

**Skill**: `skill/SKILL.md` describes the CLI workflow for a Claude agent that can
run shell commands. Point your skills directory at it (or copy it in).

Both adapters are thin wrappers over `pdfscan.service.ScannerService`, so behavior
is identical across CLI, MCP, and Skill.

## Architecture

```
service/   core facade (CLI + MCP + Skill all call this)
config/    settings + veraPDF ignore-rule profiles
models/    dataclasses
db/        sqlite engine, schema, repositories
scraper/   single generic Scrapy spider, pipelines, playwright middleware
resolvers/ Box (+ future Drive/SharePoint) special-case URL resolution
pdf/       download, verapdf, analyze, hashing, verify
storage/   per-site remediation folder layout
pipeline/  orchestrator, resume, 404 refresh, archive heuristics
exporters/ csv / excel / json
cli/       Typer command surface
mcp/       MCP server (M8)
utils/     url scope, http, logging, paths, tool checks
```
