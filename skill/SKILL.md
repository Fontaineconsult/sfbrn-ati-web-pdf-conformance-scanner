---
name: pdfscan
description: Crawl a website (scoped to a host/subdomain) for PDFs and verify their PDF/UA accessibility with veraPDF. Use when asked to scan a site for PDFs, audit PDF accessibility, find untagged/image-only PDFs, or export a PDF accessibility inventory.
---

# pdfscan — website PDF accessibility scanner

Drive the `pdfscan` CLI to discover PDFs on a website and check accessibility.
Run commands from the project root (where `config/settings.yaml` lives), or set
`PDFSCAN_CONFIG` / `PDFSCAN_DB_PATH`.

## Easy mode (recommended for a fresh start)
```
pdfscan init             # guided: makes a session workspace, the DB, checks
                         # Java/veraPDF (offers to install veraPDF), then adds sites
```
Non-interactive form: `pdfscan init <name> --root <dir> --site hr=https://hr.sfsu.edu -y`.

## One-time setup (manual)
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
5. **Export**: `pdfscan export html <name> --out report.html` (or `csv` / `json` / `excel`)

Or run the whole pipeline at once:
```
pdfscan run <name> --export html --export csv
```

## Scan sessions (isolated, relocatable workspaces)
Keep each audit's data out of the repo and apart from other audits. A session is
a named workspace (its own database + exports + saved PDFs) rooted anywhere on disk.
```
pdfscan session add <name> <root> --use   # register + activate (creates the folder)
pdfscan session list            # all sessions; active marked with *
pdfscan session use <name>      # switch the active session (--clear to deactivate)
pdfscan session show [<name>]   # metadata + resolved output paths (default: active)
pdfscan session remove <name>   # unregister (files on disk are left alone)
pdfscan paths                   # show where every output currently resolves
```
`pdfscan init` is the easiest way to create one. The session registry lives at
`~/.pdfscan/sessions.yaml` (override with `PDFSCAN_SESSIONS_FILE`). Once a session
is active, all `crawl`/`verify`/`export`/`status`/`site` commands read & write only
under it. For a one-off, prefix any command with `--session <name>` (or
`--session-root <path>`) instead of switching the active one. With no session
selected, outputs stay in the project.

## Other tools
- `pdfscan archive test <url>` — check whether the archive heuristics flag a URL (no scan).
- `pdfscan archive apply <name>` — flag archived-looking PDFs in the DB.
- `pdfscan check-404 <name>` — refresh dead-link status.
- `pdfscan site list` / `pdfscan site show <name>` / `pdfscan site remove <name>`.

## Interpreting results
`status` and exports report, per PDF: `tagged` (false = not tagged, a hard fail),
`image_only` (needs OCR), `violations` / `failed_checks` (veraPDF PDF/UA), `page_count`,
`title_set`, `language_set`, `offsite`, and `local_path` (saved remediation copy).

## Other useful commands
- `pdfscan whois <name>` — who owns/maintains a site (owner org + people).
- `pdfscan rules <name> <url-substring>` — veraPDF per-rule breakdown for matching PDFs.
- `pdfscan eval <dir>` — score the remediation classifier against pre-sorted PDFs.

## Programmatic / MCP
The same operations are exposed over MCP via the `pdfscan-mcp` server (29 tools,
including `add_site`, `crawl_site`, `verify_site`, `run_pipeline`, `site_status`,
`pdf_rules`, `export_results`, `archive_site`, `check_404`, `test_archive_rule`,
`evaluate_classifier`, `doctor`, `output_paths`, and the ownership/people tools).
All commands also work through `pdfscan.service.ScannerService` in Python.
