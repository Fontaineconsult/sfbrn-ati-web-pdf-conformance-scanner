# pdfscan — Website PDF Accessibility Scanner

Crawl any website for PDFs, save them for remediation, and verify their
accessibility (**PDF/UA**, ISO 14289) with a bundled **veraPDF** — then triage
every PDF into *good-to-go*, *fit-for-automated-tagging*, or
*needs-manual-remediation* and export shareable reports.

A generalized rebuild of the SF State PDF website scanner: one config-driven
Scrapy spider (no per-site spider generation), pluggable special-case resolvers
(Box.com first), scrapy-playwright for JS-rendered sites, SQLite persistence, and
CSV / Excel / JSON / HTML outputs. The same core is driven identically from the
**CLI**, a **Claude Desktop MCP server**, and a **Skill** — all thin adapters
over `pdfscan.service.ScannerService`.

---

## Features

**Discovery & crawling**
- One generic, config-driven Scrapy spider — scope a crawl to a `host`,
  `subdomain`, `domain`, or URL `path`.
- JS-rendered sites via Playwright/Chromium (`--render`).
- Special-case resolvers (Box.com share links → real PDFs); pluggable.
- Optional off-site PDF capture, depth/page/time caps, polite autothrottling.

**Accessibility verification**
- Bundled **veraPDF** (auto-downloaded + headlessly installed) runs PDF/UA checks.
- Acrobat-safe **ignore profiles** so known-noise rules don't inflate violations;
  inspect per-rule results with `pdfscan rules`.
- Per-PDF analysis: tagged / image-only / title / language / page count / forms.

**Remediation triage (three-signal classifier)**
- Every PDF is labeled **good_to_go**, **fit_for_automated_tagging**, or
  **needs_manual_remediation** — applied at *read time* from
  `config/classification.yaml`, so re-tuning the policy re-labels with no
  re-verify. Score the policy against pre-sorted PDFs with `pdfscan eval`.

**Ownership & accountability**
- Track org-level **site owners** and the **people** responsible (many-to-many,
  with a manager flag). Bulk-load rosters from CSV (`pdfscan people import`).
- `pdfscan whois <site>` → who to contact.

**Isolated, relocatable workspaces (sessions)**
- A **session** relocates *all* outputs (database, saved PDFs, exports, scratch)
  under one folder anywhere on disk — each audit a self-contained workspace with
  its own database. Or relocate piecemeal with `--output-root` / per-output flags.

**Outputs**
- Exports: **CSV / JSON / Excel / HTML** (the HTML report is status-demarcated
  for sharing). Coverage summary or rich per-PDF table via `pdfscan status`.

**Easy mode**
- `pdfscan init` — one guided command: name a session, pick a folder, create the
  DB, check Java/veraPDF (offering to install veraPDF), then add sites.

---

## Requirements

- **Python ≥ 3.12** (developed on 3.14)
- **Java 8+** on `PATH` (veraPDF is a Java application)
- **Internet access on first run** (to download veraPDF and, for JS crawls, Chromium)

## Install

```powershell
# from the repo root, with the project venv active
python -m pip install -e ".[dev]"
python -m playwright install chromium     # only needed for --render (JS) crawls
```

`pip install` puts two commands on your PATH: `pdfscan` (the CLI) and
`pdfscan-mcp` (the MCP server).

---

## Getting started

### The fast path — `pdfscan init` (recommended)

One guided command stands up a ready-to-scan workspace and waits for your sites:

```powershell
pdfscan init
```

It will:
1. Ask for a **session name** and a **workspace folder** (all outputs go there).
2. Create + activate the session and **create/migrate its database**.
3. **Check Java + veraPDF** — and offer to install veraPDF if it's missing.
4. Prompt you to **add sites** (name + seed URL) until you press Enter on a blank
   name, then print the next steps.

Non-interactive / scriptable form:

```powershell
pdfscan init audit --root "D:/PDF Scans/audit" --label "Q2 audit" `
  --site hr=https://hr.sfsu.edu --site news=https://news.example -y
```

Because `init` activates the session, plain `pdfscan …` commands target that
workspace from then on.

### The manual path

```powershell
pdfscan db init                                   # create the SQLite database
pdfscan doctor                                    # confirm Java / veraPDF / Chromium
pdfscan setup-verapdf                             # if doctor reports veraPDF missing

pdfscan site add hr --seed https://hr.sfsu.edu --scope host --depth 0
pdfscan crawl hr                                  # discover PDFs
pdfscan verify hr                                 # download + veraPDF + analyze + save copies
pdfscan status hr                                 # coverage + triage summary
pdfscan export html hr --out hr.html              # shareable report
```

Or run the whole pipeline at once:

```powershell
pdfscan run hr --export html --export csv         # crawl → verify → archive → export
```

---

## Sessions & output locations

By default every output lives in the project folder. You can relocate outputs
three ways (highest precedence wins):

| Scope | How |
|---|---|
| Everything, named & remembered | a **session** (`pdfscan init` / `pdfscan session …`) |
| Everything, ad-hoc this run | `--output-root <dir>` or `PDFSCAN_OUTPUT_ROOT` |
| One output at a time | `--db` / `--export-dir` / `--storage-root` (+ matching env vars) |

A session = a named `output_root`, so it relocates **all** of: the database
(`data/pdfscan.db`), saved PDF copies (`remediation/`), exports (`exports/`), and
scratch (`.scratch/`). veraPDF stays vendored in the project (it's an input, not
an output). Inspect where everything resolves with **`pdfscan paths`**.

**Selection precedence** (highest first): `--session` / `--session-root` →
`PDFSCAN_SESSION` / `PDFSCAN_SESSION_ROOT` → the registry's active session → none
(project-local). An explicit `--output-root` / `PDFSCAN_OUTPUT_ROOT` always wins
over a session.

The session registry is a small YAML file at **`~/.pdfscan/sessions.yaml`**
(override with `PDFSCAN_SESSIONS_FILE`). Because a session root is an absolute,
machine-specific path, keep the registry per-environment.

```powershell
pdfscan session add audit "D:/PDF Scans/audit" --use --label "Q2 audit"
pdfscan session list                  # all sessions; the active one marked with *
pdfscan session show audit            # metadata + resolved output paths
pdfscan --session audit run hr        # one-off: use a session for a single command
pdfscan session use --clear           # back to project-local outputs
```

---

## Command reference

Global options (before the command): `--config PATH`, `--db PATH`,
`--session NAME`, `--session-root PATH`, `--output-root PATH`, `--export-dir PATH`,
`--storage-root PATH`, `-v/--verbose`.

### Setup & environment
| Command | What it does |
|---|---|
| `pdfscan init [NAME] [--root DIR] [--label T] [--site NAME=URL ...] [-y]` | Easy-mode wizard: session + DB + tooling check + add sites |
| `pdfscan doctor` | Check Java, veraPDF, and Playwright/Chromium |
| `pdfscan setup-verapdf [--force]` | Download + headlessly install the bundled veraPDF |
| `pdfscan paths` | Show where each output (db/exports/remediation/scratch) resolves |
| `pdfscan version` | Print the version |

### Database — `pdfscan db`
| Command | What it does |
|---|---|
| `db init` | Create the database + schema (idempotent) |
| `db migrate` | Apply pending schema migrations |
| `db vacuum` | Compact the database file |

### Sessions — `pdfscan session`
| Command | What it does |
|---|---|
| `session add NAME ROOT [--label T] [--notes N] [--use]` | Register (and optionally activate) a workspace; creates the folder |
| `session list` | List sessions; active marked `*` |
| `session use [NAME] [--clear]` | Set or clear the active session |
| `session show [NAME]` | Show a session's details + resolved output paths (default: active) |
| `session remove NAME` | Unregister a session (files on disk are left alone) |

### Sites — `pdfscan site`
| Command | What it does |
|---|---|
| `site add NAME --seed/-s URL ...` | Add/update a site (see options below) |
| `site list` | List configured sites + PDF counts |
| `site show NAME` | Full site configuration |
| `site set-owner NAME [OWNER_KEY] [--clear]` | Assign/clear the responsible owner org |
| `site remove NAME` | Remove a site and its discovered PDFs |

`site add` options: `--seed/-s` (repeatable, required), `--host` (allowed
host(s); defaults to seed hosts), `--scope host|subdomain|domain|path`,
`--depth N` (0 = unlimited), `--render/--no-render`,
`--obey-robots/--no-obey-robots`, `--delay S`, `--concurrency N`,
`--resolver NAME` (repeatable, e.g. `box`),
`--include-offsite-pdfs/--no-include-offsite-pdfs`, `--path-prefix P` (scope=path),
`--storage-template T`, `--owner KEY`, `--notes N`.

### Scan — top-level
| Command | What it does |
|---|---|
| `crawl NAME` | Discover PDFs. Run-only overrides: `--render`, `--obey-robots`, `--delay`, `--concurrency`, `--depth`, `--include-offsite-pdfs`, `--max-pages N`, `--timeout S` |
| `verify NAME` | Download + veraPDF + analyze. `--refresh` (re-verify reported PDFs), `--limit N`, `--save/--no-save` |
| `run NAME` | Full pipeline. `--no-crawl`, `--no-verify`, `--no-archive`, `--check-404`, `--export csv\|json\|excel\|html` (repeatable), plus the `crawl`/`verify` overrides + `--limit` |
| `status NAME` | Summary, or `--table/-t` for a per-PDF table. `--filter/-f`, `--sort url\|violations`, `--limit/-n` |
| `rules NAME URL` | veraPDF per-rule results for PDFs whose URL contains `URL`. `--limit/-n` |
| `check-404 NAME` | Refresh dead-link (404) status for PDFs + parent pages |

`status --filter` values: `all`, `verified`, `pending`, `issues`, `offsite`,
`archived`, `broken`, `good_to_go`, `auto`, `manual`.

### Exports — `pdfscan export`
| Command | What it does |
|---|---|
| `export csv\|json\|excel\|html [SITE] --out/-o PATH [--all]` | Write a report for one site (or `--all` sites) |

### Archive heuristics — `pdfscan archive`
| Command | What it does |
|---|---|
| `archive apply NAME` | Flag archived-looking PDFs (sets `archived`) |
| `archive test [URL] [--from-file PATH]` | Dry-run the archive rules against URLs (no scan) |

### Ownership & people
| Command | What it does |
|---|---|
| `owner add KEY [--label T] [--notes N]` / `owner list` / `owner show KEY` / `owner remove KEY` | Manage org-level site owners |
| `person add EMP_ID FULL_NAME [--email E] [--manager]` / `person list` / `person remove EMP_ID` | Manage people |
| `person assign EMP_ID OWNER_KEY` / `person unassign EMP_ID OWNER_KEY` | Membership in an owner org |
| `whois NAME` | Show a site's owner + responsible people |
| `people import [--sites] [--employees] [--managers] [--assignments]` | Bulk-load rosters from CSV |

### Classifier calibration
| Command | What it does |
|---|---|
| `eval PATH [--profile P.yaml] [--json OUT]` | Score the classifier against pre-sorted PDFs (subfolders `good_to_go/`, `fit_for_automated_tagging/`, `needs_manual_remediation/`); prints accuracy, confusion matrix, and mismatches |

---

## Understanding the results

`status` and the exports report, per PDF:

- **tagged** — has a logical structure tree. `false` is a hard PDF/UA fail.
- **image_only** — scanned/image PDF with no real text (needs OCR); veraPDF is
  authoritative here.
- **violations / failed_checks** — counted PDF/UA rule failures (after the
  acrobat-safe ignore profile is applied).
- **title_set / language_set / page_count / has_form** — metadata + content signals.
- **offsite / via_resolver / archived / 404** — crawl provenance and link health.
- **local_path** — the saved remediation copy (under `remediation/<site>/…`).

Each PDF's **remediation class** is derived from those signals:

- **good_to_go** — tagged, no counted violations, not image-only → likely accessible.
- **fit_for_automated_tagging** — structurally simple; a tagging tool can likely fix it.
- **needs_manual_remediation** — image-only / complex / form-bearing → needs a human.

The thresholds live in `config/classification.yaml`; editing it re-labels existing
results with no re-verify. Use `pdfscan eval` to tune it against ground truth.

---

## Configuration

Global settings live in `config/settings.yaml`; per-site config lives in the
database. Precedence: **CLI flag > env (`PDFSCAN_*`) > settings.yaml > built-in
defaults**.

**Environment variables**

| Variable | Effect |
|---|---|
| `PDFSCAN_CONFIG` | Path to `settings.yaml` |
| `PDFSCAN_OUTPUT_ROOT` | Relocate all outputs under one folder |
| `PDFSCAN_DB_PATH` | Database path |
| `PDFSCAN_EXPORT_DIR` | Reports/exports folder |
| `PDFSCAN_STORAGE_ROOT` | Saved-PDF (remediation) folder |
| `PDFSCAN_TEMP_DIR` | Scratch folder |
| `PDFSCAN_SESSION` / `PDFSCAN_SESSION_ROOT` | Select a session / ad-hoc workspace |
| `PDFSCAN_SESSIONS_FILE` | Session registry location |
| `PDFSCAN_VERAPDF` | Explicit veraPDF executable path |

**Other policy files** (resolved against the project, tolerant of being absent):
`config/ignore_profiles.yaml` (acrobat-safe veraPDF rules) and
`config/classification.yaml` (the triage policy). The remediation storage path is
a template — default `{root}/{site}/{hash}.pdf` (content-addressed → dedup on
identical bytes); tokens: `{root} {site} {path} {filename} {hash} {date}`.

---

## Claude Desktop (MCP) & Skill

Both adapters are thin wrappers over `pdfscan.service.ScannerService`, so behavior
is identical across CLI, MCP, and Skill.

**MCP server** (`pdfscan-mcp`, stdio). Add to your Claude Desktop config:

```json
{
  "mcpServers": {
    "pdfscan": {
      "command": "C:\\path\\to\\sfbrn-pdf-scanner\\.venv\\Scripts\\pdfscan-mcp.exe",
      "env": {
        "PDFSCAN_CONFIG": "C:\\path\\to\\sfbrn-pdf-scanner\\config\\settings.yaml",
        "PDFSCAN_SESSION": "audit"
      }
    }
  }
}
```

The server auto-migrates the database on start and exposes **29 tools**, including:
`doctor`, `db_status`, `output_paths`, `setup_verapdf`, `list_sites`, `add_site`,
`remove_site`, `site_status`, `pdf_rules`, `crawl_site`, `verify_site`,
`run_pipeline`, `export_results`, `archive_site`, `check_404`,
`test_archive_rule`, `evaluate_classifier`, and the ownership tools (`list_owners`,
`add_owner`, `show_owner`, `remove_owner`, `set_site_owner`, `whois`,
`list_people`, `add_person`, `remove_person`, `assign_person`, `unassign_person`,
`import_people`). `crawl_site` and `run_pipeline` shell out to the CLI so Scrapy's
reactor never clashes with the MCP event loop.

**Skill**: `skill/SKILL.md` describes the CLI workflow for a Claude agent that can
run shell commands.

---

## Architecture

```
service/   core facade (CLI + MCP + Skill all call this)
config/    settings, session registry, veraPDF ignore + classification profiles
models/    dataclasses
db/        sqlite engine, schema, versioned migrations, repositories
scraper/   single generic Scrapy spider, pipelines, playwright middleware
resolvers/ Box (+ future Drive/SharePoint) special-case URL resolution
pdf/       download, veraPDF, analyze, hashing, verify
classify/  three-signal remediation classifier + eval harness
people/    CSV roster importer (owners / people / assignments)
storage/   content-addressed remediation file layout
pipeline/  archive heuristics, 404 refresh
exporters/ csv / json / excel / html
cli/       Typer command surface
mcp/       MCP server (framework-agnostic handlers + FastMCP adapter)
utils/     url scope, http, tool checks
```

---

## Development

```powershell
python -m pytest -q                       # test suite
ruff check src/pdfscan tests              # lint
```

The CLI, MCP, and Skill must stay thin: new behavior belongs in
`pdfscan.service.ScannerService` so all three surfaces inherit it.
