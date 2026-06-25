# PDF Verify — Improvement Plan

Tracking the agreed improvements to the verify pipeline (`pdf/verify.py`,
`pdf/verapdf.py`, `pdf/analyze.py`, `db/…`). Worked one phase at a time; each
phase lands with tests + ruff clean before moving on.

Status: ☐ todo · ◐ in progress · ☑ done

---

## Phase 1 — Persist per-rule veraPDF results  ☑ (schema v2)
**Why:** Today `pdf_report` keeps only aggregates (`violations` count,
`failed_checks` sum, `tagged`, `image_only`). The per-rule detail veraPDF
produces is discarded, so we can't answer *"what is wrong with this PDF?"* and
changing `ignore_profiles.yaml` requires a full re-download + re-run to re-score.
This is the highest-value change for a remediation tool.

**Decision (resolved):** normalized `report_rule` table (no raw blob).

**Landed:**
- `report_rule` table (clause, test_number, status, failed_checks, specification,
  description) + `ix_report_rule_hash`, FK→`pdf_report(pdf_hash)` ON DELETE
  CASCADE. `SCHEMA_VERSION` → 2; `db migrate` adds it to existing DBs.
- `pdf/verapdf.py` split into `extract_rules()` (verbatim, policy-free) +
  `summarize()` (applies ignore policy); `parse_verapdf()` kept as a wrapper.
- `ReportRepository.replace_rules()` / `list_rules()`; `verify_pdf` persists all
  rules on a fresh veraPDF run.
- New `pdfscan rules <site> <url-substr>` view: per-rule table annotated with the
  current ignore policy (ignored / counts / flag), applied at **read time** — so
  editing `ignore_profiles.yaml` re-scores the view with no re-download.
- Tests: extract/summarize equivalence + optional-field capture; repo round-trip,
  replace-supersedes, cascade-on-delete. 94 passing, ruff clean.

**Follow-ups (deferred, not blocking):**
- Stored rules are written on the *verified* path only; pre-v2 reports and
  `reused` hashes won't backfill rules until a `verify --refresh`.
- Add a `verify --rescore` that recomputes `pdf_report` aggregates from stored
  rules under the current ignore profile (no download) — the natural payoff of
  this schema; not yet implemented.
- Exporters don't yet include per-rule detail.

**Approach (proposed):** add a normalized `report_rule` table (one row per
failing rule), populated from the veraPDF report. The stored `pdf_report`
aggregates stay (fast summary), but become *derivable* from the rules + ignore
policy. Schema shape is the one open decision — see "Decisions" below.

**Changes:**
- `db/schema.py` — new `report_rule(pdf_hash, clause, test_number, status,
  failed_checks, specification, description)` + index on `pdf_hash`; bump
  `SCHEMA_VERSION`.
- `db/migrations.py` — `create_all` handles the new table via IF NOT EXISTS;
  add a `version < N` block to bump the stamp.
- `pdf/verapdf.py` — extend parse to return per-rule records alongside the
  summary (keep ignore-policy application, but also retain raw rule rows).
- `db/repositories/reports.py` (or new `RuleRepository`) — bulk-insert rules
  for a hash; replace-on-reverify.
- `pdf/verify.py` — persist rules when a report is computed.
- Surfacing: `pdfscan status <site> --pdf <url>` (or `--rules`) detail view +
  rules in exporters.
- Tests: parse → rule extraction, repo insert/replace, ignore-policy still
  reflected in aggregates.

**Acceptance:** after verify, the failing clauses/tests for a PDF are queryable;
re-running with a changed ignore profile reproduces aggregates from stored rules
without re-downloading (stretch goal — at minimum the data is persisted).

### Decisions (Phase 1)
- **Storage shape** — normalized `report_rule` table *(recommended)* vs raw
  JSON blob on `pdf_report` vs both. → **pending user confirm.**

---

## Phase 2 — Correctness & robustness fixes  ☑
**Decision (resolved):** dedupe storage **by content hash**. A URL is not a
stable identity for content (a file can be replaced at the same URL), so the
default remediation template is now content-addressed.

**Landed:**
- **Dedupe by hash:** default `storage.template` → `{root}/{site}/{hash}.pdf`
  (both `settings.py` DEFAULTS and `settings.yaml`). `save_pdf` skips the copy
  when the dest already exists → identical bytes stored once, and a replaced
  file (new hash) lands at a new path instead of clobbering the old copy.
- **Temp-file leak:** download-failure branch now `_cleanup(temp_path)`.
- **`%PDF-` magic-byte gate:** `looks_like_pdf()` (lenient, scans first 1 KiB)
  runs right after download; a `.pdf` URL that served HTML records a distinct
  "not a PDF (content)" failure instead of crashing veraPDF.
- **Encrypted PDFs:** `analyze.is_encrypted()`; when structural analysis returns
  `None` and the file is password-protected, a clear "encrypted (structural
  analysis skipped)" failure is recorded (no longer silent). veraPDF results are
  still stored.
- **Skip known 404s:** `list_unverified` now excludes `pdf_404 = 1` rows.
- Tests: save dedup + replacement, magic gate (incl. BOM/whitespace + missing),
  encrypted round-trip (real pikepdf-encrypted PDF), 404-skip. 104 passing,
  ruff clean.

**Note:** a URL-path template (`{root}/{site}/{path}/{filename}`) is still
available for browsable layouts but opts out of dedup (and can clobber on
replacement) — documented in `settings.yaml`.

---

## Phase 3 — Reconcile image-only signals  ☑
**Decision (resolved):** veraPDF clause 7.1/3 (`image_only`) is **authoritative**;
pdfminer `text_type` is kept as a **diagnostic only**.

**Landed:**
- Codified the policy in docstrings (`models/report.py` `PdfReport`,
  `analyze.py` `text_type` / `_pdf_text_type`) so it isn't reintroduced as a
  second verdict.
- Status table: `Img` is the authoritative image-only column; the `Text` column
  marks pdfminer's `"Image Only"` with `?` (dim) when it disagrees with the
  authoritative flag (`_text_type_cell`). Legend updated accordingly.
- The status summary's image-only count already derives solely from the veraPDF
  flag (unchanged).
- Tests: pass-through, agreement, disagreement-marking, None. 107 passing, ruff
  clean.

**Note:** consciously accepts the trade-off that pdfminer-only "Image Only"
catches (PDFs veraPDF doesn't flag) are surfaced as a diagnostic `?`, not a
verdict.

---

## Phase 4 — Performance  ☑
**Target scale (resolved):** hundreds of PDFs per site.

**Landed — `verify_site()` chunked pipeline** (replaces the serial per-file loop
in `facade.verify`):
- **Batched veraPDF:** one JVM invocation per chunk over the chunk's unique new
  files (`run_verapdf_batch`, results mapped back by basename) — turns ~N JVM
  cold starts into ~N/`batch_size`. Per-file fallback if a batch call fails.
- **Parallel downloads:** `ThreadPoolExecutor` (`verify.download_workers`,
  default 8) overlaps network latency; downloads are DB-free and thread-safe.
- **URL dedup:** identical URLs in a chunk download once; **content dedup:**
  identical sha256 validated once (reuses the report, as before).
- **Chunked** by `verify.batch_size` (default 50) so temp disk is bounded to one
  chunk; DB writes stay on the calling thread and **commit per chunk** (resumable).
- Counts match the per-file semantics (one `verified` per fresh hash, rest
  `reused`); failures isolated per URL / per hash.
- Config: `verify.{download_workers,batch_size,batch_timeout}` in `settings.py`
  DEFAULTS + `settings.yaml`. Shared `_make_report` keeps the single- and
  batch-path report building identical.
- Tests: batch parse (basename mapping, empty, bad-JSON), a **real veraPDF**
  batch run over pikepdf-generated PDFs (skips without the binary), and a full
  `verify_site` orchestration test (stubbed download/veraPDF) covering URL dedup,
  content reuse, failure isolation, counts, persistence, and content-addressed
  saves. 112 passing, ruff clean.

**Deferred:** gating the pdfminer text-type pass (second parse) and a true
URL-reuse-without-download fast path were not needed at hundreds-scale.

---

## Open questions
1. ~~Phase 1 storage shape~~ → resolved: normalized `report_rule` table.
2. ~~Phase 4 target scale~~ → resolved: hundreds per site.
3. ~~Phase 2 duplicate-save~~ → resolved: dedupe by content hash (content-addressed).

All four phases complete. Remaining deferred follow-ups live inline per phase
(notably: `verify --rescore` from stored rules, exporters' per-rule detail).
