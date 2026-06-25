"""Read-time glue: classify ``export_rows`` dicts against the stored per-rule data.

Pairs each verified row with its counted veraPDF rules (loaded from
``report_rule`` and filtered through the ignore policy) and runs the pure
:func:`~pdfscan.classify.classifier.classify_pdf`. Read-only; recomputes per call
(cheap at hundreds-of-PDFs scale), so editing either policy file re-classifies
with no re-verify.
"""

from __future__ import annotations

import sqlite3

from pdfscan.classify.classifier import Classification, classify_pdf
from pdfscan.classify.profile import ClassificationProfile
from pdfscan.config import IgnoreProfiles
from pdfscan.db.repositories import ReportRepository
from pdfscan.models import ReportRule


def classify_rows(
    conn: sqlite3.Connection,
    rows: list[dict],
    ignore: IgnoreProfiles,
    profile: ClassificationProfile,
) -> dict[str, Classification]:
    """Map ``pdf_url -> Classification`` for the given joined rows.

    Rows sharing a ``file_hash`` reuse one cached rule lookup. Unverified rows
    (no violations / no hash) classify as ``pending`` with no DB read.
    """
    reports = ReportRepository(conn)
    counted_by_hash: dict[str, list[ReportRule]] = {}
    out: dict[str, Classification] = {}

    for row in rows:
        file_hash = row.get("file_hash")
        if row.get("violations") is None or not file_hash:
            counted: list[ReportRule] = []
        else:
            if file_hash not in counted_by_hash:
                counted_by_hash[file_hash] = [
                    r
                    for r in reports.list_rules(file_hash)
                    if not ignore.is_ignored(r.clause, r.test_number)
                ]
            counted = counted_by_hash[file_hash]
        out[row["pdf_url"]] = classify_pdf(row, counted, profile)

    return out
