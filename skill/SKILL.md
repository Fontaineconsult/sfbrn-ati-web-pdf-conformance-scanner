---
name: pdfscan
description: Crawl a website (scoped to a host/subdomain) for PDFs and verify their PDF/UA accessibility with veraPDF. Use when asked to scan a site for PDFs, audit PDF accessibility, find untagged/image-only PDFs, or export a PDF accessibility inventory.
---

# pdfscan — website PDF accessibility scanner

Drive the `pdfscan` CLI to discover PDFs on a website and check accessibility.
Run commands from the project root (where `config/settings.yaml` lives), or set
`PDFSCAN_CONFIG` / `PDFSCAN_DB_PATH`.

## One-time setup
```
pdfscan db init          # create the SQLite database
pdfscan doctor           # confirm Java + veraPDF + Chromium
pdfscan setup-verapdf    # if doctor reports veraPDF missing
```

## Core workflow
1. **Add a site** (scope it to one host by default):
   ```
   pdfscan site add <name> --seed https://<host> --scope host --depth 3
   ```
   - `--scope` = `host` (one subdomain, default) | `subdomain` | `domain` | `path`
   - `--render` to render JS (Playwright) for SPA sites
   - `--include-offsite-pdfs` to also capture PDFs hosted off the host
   - `--resolver box` to resolve Box.com share links to real PDFs
2. **Crawl** for PDFs: `pdfscan crawl <name>` (add `--max-pages N` / `--timeout S` to bound it)
3. **Verify** accessibility: `pdfscan verify <name>` (downloads, runs veraPDF, saves copies for remediation under `remediation/<site>/...`)
4. **Inspect**: `pdfscan status <name>`
5. **Export**: `pdfscan export excel <name> --out report.xlsx` (or `csv` / `json`)

Or run the whole pipeline at once:
```
pdfscan run <name> --export excel --export json
```

## Scan sessions (isolated, relocatable workspaces)
Keep each audit's data out of the repo and apart from other audits. A session is
a named workspace (its own database + exports + saved PDFs) rooted anywhere on disk.
```
pdfscan session add <name> --root <path> --use --init   # register, activate, create DB
pdfscan session list            # all sessions; active marked with *
pdfscan session current         # active session, or "project-local"
pdfscan session use <name>      # switch the active session
pdfscan session show <name>     # metadata + resolved output paths
pdfscan session path [<name>]   # print a session's root (scriptable)
pdfscan session remove <name> [--delete-files]
```
Once a session is active, all `crawl`/`verify`/`export`/`status`/`site` commands
read & write only under it. For a one-off, prefix any command with
`--session <name>` (or `--session-root <path>`) instead of switching the active one.
With no session selected, behavior is unchanged (outputs stay in the project).

## Other tools
- `pdfscan archive test <url>` — check whether the archive heuristics flag a URL (no scan).
- `pdfscan archive apply <name>` — flag archived-looking PDFs in the DB.
- `pdfscan check-404 <name>` — refresh dead-link status.
- `pdfscan site list` / `pdfscan site show <name>` / `pdfscan site remove <name>`.

## Interpreting results
`status` and exports report, per PDF: `tagged` (false = not tagged, a hard fail),
`image_only` (needs OCR), `violations` / `failed_checks` (veraPDF PDF/UA), `page_count`,
`title_set`, `language_set`, `offsite`, and `local_path` (saved remediation copy).

## Programmatic / MCP
The same operations are exposed over MCP via the `pdfscan-mcp` server (tools:
`add_site`, `crawl_site`, `verify_site`, `run_pipeline`, `site_status`,
`export_results`, `test_archive_rule`, `doctor`). All commands also work through
`pdfscan.service.ScannerService` in Python.
