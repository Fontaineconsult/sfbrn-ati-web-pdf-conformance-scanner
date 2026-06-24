"""Verify one PDF: download -> hash -> (save for remediation) -> veraPDF + analyze -> store.

Identical content (same sha256) reuses the existing pdf_report instead of
re-running veraPDF, matching the original tool's hash-based dedup.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from pdfscan.config import IgnoreProfiles, Settings
from pdfscan.db.repositories import FailureRepository, PdfRepository, ReportRepository
from pdfscan.models import Failure, PdfFile, PdfReport
from pdfscan.pdf.analyze import analyze_pdf
from pdfscan.pdf.download import download_to_file
from pdfscan.pdf.hashing import sha256_file
from pdfscan.pdf.verapdf import parse_verapdf, run_verapdf
from pdfscan.storage import save_pdf


@dataclass
class VerifyOutcome:
    status: str  # "verified" | "reused" | "failed"
    pdf_id: int
    file_hash: str | None = None
    error: str | None = None


def _cleanup(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


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
        failures.add(Failure(pdf.site_id, pdf.id, f"download {pdf.pdf_url}: {exc}"))
        return VerifyOutcome("failed", pdf.id, error=str(exc))

    # 2. hash
    file_hash = sha256_file(temp_path)

    # 3. save a remediation copy (non-fatal on failure)
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

    # 4. reuse existing report for identical content
    if reports.exists_for_hash(file_hash):
        pdfs.set_verified(pdf.id, file_hash, local_path)
        _cleanup(temp_path)
        return VerifyOutcome("reused", pdf.id, file_hash=file_hash)

    # 5. veraPDF + structural analysis
    try:
        report_json = run_verapdf(
            temp_path,
            verapdf_cmd,
            flavour=str(settings.get("verapdf.flavour", "ua1")),
            timeout=int(settings.get("verapdf.timeout", 180)),
        )
        vera = parse_verapdf(report_json, ignore)
    except Exception as exc:
        failures.add(Failure(pdf.site_id, pdf.id, f"verapdf {pdf.pdf_url}: {exc}"))
        _cleanup(temp_path)
        return VerifyOutcome("failed", pdf.id, error=str(exc))

    analysis = analyze_pdf(temp_path)
    report = PdfReport(
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
    reports.upsert(report)
    pdfs.set_verified(pdf.id, file_hash, local_path)
    _cleanup(temp_path)
    return VerifyOutcome("verified", pdf.id, file_hash=file_hash)
