"""Verify one PDF: download -> hash -> (save for remediation) -> veraPDF + analyze -> store.

Identical content (same sha256) reuses the existing pdf_report instead of
re-running veraPDF, matching the original tool's hash-based dedup.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from pdfscan.config import IgnoreProfiles, Settings
from pdfscan.db.repositories import FailureRepository, PdfRepository, ReportRepository
from pdfscan.models import Failure, PdfFile, PdfReport
from pdfscan.pdf.analyze import PdfAnalysis, analyze_pdf, is_encrypted
from pdfscan.pdf.download import download_to_file
from pdfscan.pdf.hashing import sha256_file
from pdfscan.pdf.verapdf import (
    VeraSummary,
    extract_rules,
    rules_from_job,
    run_verapdf,
    run_verapdf_batch,
    summarize,
)
from pdfscan.storage import save_pdf


@dataclass
class VerifyOutcome:
    status: str  # "verified" | "reused" | "failed"
    pdf_id: int
    file_hash: str | None = None
    error: str | None = None


def _make_report(
    file_hash: str, vera: VeraSummary, analysis: PdfAnalysis | None
) -> PdfReport:
    """Combine veraPDF summary + structural analysis into a ``PdfReport`` row."""
    return PdfReport(
        pdf_hash=file_hash,
        violations=vera.violations,
        failed_checks=vera.failed_checks,
        tagged=vera.tagged,
        image_only=vera.image_only,
        text_type=analysis.text_type if analysis else None,
        title_set=analysis.title_set if analysis else False,
        language_set=analysis.language_set if analysis else False,
        page_count=analysis.page_count if analysis else None,
        has_form=analysis.has_form if analysis else False,
    )


def _cleanup(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def looks_like_pdf(path: Path) -> bool:
    """True if the file carries the ``%PDF-`` marker near its start.

    Lenient like real PDF readers: the marker may sit within the first 1 KiB
    (some files carry a BOM or leading whitespace) rather than exactly at offset
    zero. A ``.pdf`` URL that actually served an HTML error/login page fails this.
    """
    try:
        with open(path, "rb") as fh:
            head = fh.read(1024)
    except OSError:
        return False
    return b"%PDF-" in head


def verify_pdf(
    conn: sqlite3.Connection,
    pdf: PdfFile,
    settings: Settings,
    verapdf_cmd: str,
    ignore: IgnoreProfiles,
    *,
    site_name: str,
    storage_template: str,
    save: bool = True,
) -> VerifyOutcome:
    pdfs = PdfRepository(conn)
    reports = ReportRepository(conn)
    failures = FailureRepository(conn)

    temp_dir = settings.temp_dir
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"verify_{pdf.id}.pdf"

    # 1. download
    try:
        download_to_file(
            pdf.pdf_url,
            temp_path,
            timeout=int(settings.get("download.timeout", 30)),
            max_bytes=settings.get("download.max_bytes"),
            ssl_insecure_retry=bool(settings.get("download.ssl_insecure_retry", True)),
        )
    except Exception as exc:
        _cleanup(temp_path)
        failures.add(Failure(pdf.site_id, pdf.id, f"download {pdf.pdf_url}: {exc}"))
        return VerifyOutcome("failed", pdf.id, error=str(exc))

    # 2. validate the bytes really are a PDF (a .pdf URL can serve an HTML
    #    error/login page, which would otherwise crash veraPDF downstream).
    if not looks_like_pdf(temp_path):
        _cleanup(temp_path)
        failures.add(Failure(pdf.site_id, pdf.id, f"not a PDF (content): {pdf.pdf_url}"))
        return VerifyOutcome("failed", pdf.id, error="downloaded content is not a PDF")

    # 3. hash
    file_hash = sha256_file(temp_path)

    # 4. save a remediation copy (non-fatal on failure)
    local_path: str | None = None
    if save:
        try:
            dest = save_pdf(
                temp_path,
                pdf.pdf_url,
                site_name,
                file_hash,
                root=settings.storage_root,
                template=storage_template,
            )
            local_path = str(dest)
        except Exception as exc:  # pragma: no cover - filesystem edge cases
            failures.add(Failure(pdf.site_id, pdf.id, f"save {pdf.pdf_url}: {exc}"))

    # 5. reuse existing report for identical content
    if reports.exists_for_hash(file_hash):
        pdfs.set_verified(pdf.id, file_hash, local_path)
        _cleanup(temp_path)
        return VerifyOutcome("reused", pdf.id, file_hash=file_hash)

    # 6. veraPDF + structural analysis
    try:
        report_json = run_verapdf(
            temp_path,
            verapdf_cmd,
            flavour=str(settings.get("verapdf.flavour", "ua1")),
            timeout=int(settings.get("verapdf.timeout", 180)),
        )
        rules = extract_rules(report_json)
        vera = summarize(rules, ignore)
    except Exception as exc:
        failures.add(Failure(pdf.site_id, pdf.id, f"verapdf {pdf.pdf_url}: {exc}"))
        _cleanup(temp_path)
        return VerifyOutcome("failed", pdf.id, error=str(exc))

    analysis = analyze_pdf(temp_path)
    if analysis is None and is_encrypted(temp_path):
        failures.add(
            Failure(pdf.site_id, pdf.id, f"encrypted (structural analysis skipped): {pdf.pdf_url}")
        )
    reports.upsert(_make_report(file_hash, vera, analysis))
    reports.replace_rules(file_hash, rules)
    pdfs.set_verified(pdf.id, file_hash, local_path)
    _cleanup(temp_path)
    return VerifyOutcome("verified", pdf.id, file_hash=file_hash)


# -- batched site verification -------------------------------------------------
@dataclass
class _Downloaded:
    """Result of downloading one URL (the representative row for that URL)."""

    pdf: PdfFile
    temp_path: Path | None
    file_hash: str | None
    error: str | None


def _download_one(
    pdf: PdfFile,
    temp_path: Path,
    timeout: int,
    max_bytes: int | None,
    ssl_insecure_retry: bool,
) -> _Downloaded:
    """Download + PDF-sniff + hash one URL. Thread-safe: no DB, isolated temp file."""
    try:
        download_to_file(
            pdf.pdf_url,
            temp_path,
            timeout=timeout,
            max_bytes=max_bytes,
            ssl_insecure_retry=ssl_insecure_retry,
        )
    except Exception as exc:
        _cleanup(temp_path)
        return _Downloaded(pdf, None, None, f"download {pdf.pdf_url}: {exc}")
    if not looks_like_pdf(temp_path):
        _cleanup(temp_path)
        return _Downloaded(pdf, None, None, f"not a PDF (content): {pdf.pdf_url}")
    return _Downloaded(pdf, temp_path, sha256_file(temp_path), None)


def _chunks(seq: list, size: int) -> Iterator[list]:
    size = max(1, size)
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def verify_site(
    conn: sqlite3.Connection,
    rows: Iterable[PdfFile],
    settings: Settings,
    verapdf_cmd: str,
    ignore: IgnoreProfiles,
    *,
    site_name: str,
    storage_template: str,
    save: bool = True,
    workers: int = 8,
    batch_size: int = 50,
) -> dict[str, int]:
    """Verify many PDFs efficiently: a chunked pipeline of parallel download ->
    one batched veraPDF invocation -> analyze -> serial DB writes per chunk.

    Per chunk, identical URLs are downloaded once and identical content (sha256)
    is validated once; veraPDF runs a single time over the chunk's unique new
    files (per-file fallback if that invocation fails). DB writes happen on the
    calling thread and commit per chunk, so the run stays resumable. Counts match
    the per-file path: one ``verified`` per freshly validated hash, other rows
    sharing a (new or existing) report counted ``reused``.
    """
    pdfs = PdfRepository(conn)
    reports = ReportRepository(conn)
    failures = FailureRepository(conn)

    temp_dir = settings.temp_dir
    temp_dir.mkdir(parents=True, exist_ok=True)
    dl_timeout = int(settings.get("download.timeout", 30))
    max_bytes = settings.get("download.max_bytes")
    ssl_retry = bool(settings.get("download.ssl_insecure_retry", True))
    flavour = str(settings.get("verapdf.flavour", "ua1"))
    batch_timeout = int(settings.get("verify.batch_timeout", 1800))
    single_timeout = int(settings.get("verapdf.timeout", 180))

    counts = {"verified": 0, "reused": 0, "failed": 0}
    verified_hashes: set[str] = set()  # hashes freshly veraPDF'd this run
    counted_verified: set[str] = set()  # hashes already counted once as "verified"

    for seq, chunk in enumerate(_chunks(list(rows), batch_size), 1):
        # group rows by URL so identical URLs are downloaded only once
        by_url: dict[str, list[PdfFile]] = {}
        for pdf in chunk:
            by_url.setdefault(pdf.pdf_url, []).append(pdf)
        url_temp = {url: temp_dir / f"verify_{seq}_{i}.pdf" for i, url in enumerate(by_url)}

        # 1. parallel download
        downloaded: dict[str, _Downloaded] = {}
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futs = {
                pool.submit(
                    _download_one, group[0], url_temp[url], dl_timeout, max_bytes, ssl_retry
                ): url
                for url, group in by_url.items()
            }
            for fut in as_completed(futs):
                downloaded[futs[fut]] = fut.result()

        # 2. partition: record download failures; collect unique new hashes
        new_hash_path: dict[str, Path] = {}
        new_hash_repr: dict[str, PdfFile] = {}
        for url, res in downloaded.items():
            if res.error:
                for pdf in by_url[url]:
                    failures.add(Failure(pdf.site_id, pdf.id, res.error))
                counts["failed"] += len(by_url[url])
                continue
            fh = res.file_hash
            assert fh is not None and res.temp_path is not None  # success implies both set
            if fh in verified_hashes or fh in new_hash_path or reports.exists_for_hash(fh):
                continue
            new_hash_path[fh] = res.temp_path
            new_hash_repr[fh] = by_url[url][0]

        # 3. one batched veraPDF over the chunk's unique new files (fallback per-file)
        hash_failed: dict[str, str] = {}
        if new_hash_path:
            try:
                jobs: dict[str, dict] | None = run_verapdf_batch(
                    list(new_hash_path.values()), verapdf_cmd, flavour, batch_timeout
                )
            except Exception:
                jobs = None  # whole-batch failure -> validate individually below
            for fh, path in new_hash_path.items():
                repr_pdf = new_hash_repr[fh]
                try:
                    if jobs is not None:
                        job = jobs.get(path.name)
                        if job is None:
                            raise RuntimeError("veraPDF returned no result for this file")
                        rules = rules_from_job(job)
                    else:
                        rules = extract_rules(
                            run_verapdf(path, verapdf_cmd, flavour, single_timeout)
                        )
                    vera = summarize(rules, ignore)
                    analysis = analyze_pdf(path)
                    if analysis is None and is_encrypted(path):
                        failures.add(
                            Failure(
                                repr_pdf.site_id,
                                repr_pdf.id,
                                f"encrypted (structural analysis skipped): {repr_pdf.pdf_url}",
                            )
                        )
                    reports.upsert(_make_report(fh, vera, analysis))
                    reports.replace_rules(fh, rules)
                    verified_hashes.add(fh)
                except Exception as exc:
                    hash_failed[fh] = f"verapdf {repr_pdf.pdf_url}: {exc}"

        # 4. persist per row: save remediation copy + set_verified, or fail
        for url, res in downloaded.items():
            if res.error:
                continue
            fh = res.file_hash
            if fh in hash_failed:
                for pdf in by_url[url]:
                    failures.add(Failure(pdf.site_id, pdf.id, hash_failed[fh]))
                counts["failed"] += len(by_url[url])
                continue
            for pdf in by_url[url]:
                local_path: str | None = None
                if save:
                    try:
                        local_path = str(
                            save_pdf(
                                res.temp_path,
                                pdf.pdf_url,
                                site_name,
                                fh,
                                root=settings.storage_root,
                                template=storage_template,
                            )
                        )
                    except Exception as exc:  # pragma: no cover - filesystem edge cases
                        failures.add(Failure(pdf.site_id, pdf.id, f"save {pdf.pdf_url}: {exc}"))
                pdfs.set_verified(pdf.id, fh, local_path)
                if fh in verified_hashes and fh not in counted_verified:
                    counted_verified.add(fh)
                    counts["verified"] += 1
                else:
                    counts["reused"] += 1

        # 5. cleanup this chunk's temp files, then commit (keeps the run resumable)
        for path in url_temp.values():
            _cleanup(path)
        conn.commit()

    return counts
