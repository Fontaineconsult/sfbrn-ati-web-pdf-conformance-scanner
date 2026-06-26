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

## Scan sessions (relocatable workspaces)

By default all outputs (database, saved PDF copies, exports, scratch) live in the
project folder. A **session** relocates them — together — under a named folder
**anywhere on disk**, so each audit is a self-contained, isolated workspace (its
own database) and nothing pollutes the repo.

```powershell
# Register an external workspace and make it active (creates + migrates its DB)
pdfscan session add audit --root D:/pdfscan-data/audit --use --init

# Everything now reads & writes only under D:/pdfscan-data/audit
pdfscan crawl hr
pdfscan verify hr
pdfscan export excel hr --out hr.xlsx     # -> D:/pdfscan-data/audit/...

pdfscan session list        # all sessions; the active one marked with *
pdfscan session current     # active session (or "project-local")
pdfscan session show audit  # metadata + resolved output paths
pdfscan session use sfsu    # switch the active session
pdfscan session path        # print the active root (scriptable)
```

**Selection precedence** (highest wins): `--session <name>` / `--session-root <path>`
(this run) → `PDFSCAN_SESSION` / `PDFSCAN_SESSION_ROOT` (env) → the registry's
active session → none (project-local, unchanged). An explicit `--output-root` /
`PDFSCAN_OUTPUT_ROOT` always wins over a session.

The session registry lives outside the repo — `%APPDATA%\pdfscan\sessions.yaml`
on Windows, `${XDG_CONFIG_HOME:-~/.config}/pdfscan/sessions.yaml` elsewhere
(override with `PDFSCAN_SESSIONS_FILE`). Because a session root is an absolute,
environment-specific path, keep the registry per-environment (or point a logical
session at the right local path with `PDFSCAN_SESSION_ROOT`).

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
