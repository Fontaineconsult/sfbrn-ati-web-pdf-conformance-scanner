from __future__ import annotations

import sqlite3

from pdfscan.db.repositories.base import BaseRepository
from pdfscan.models import PdfReport, ReportRule


def _row_to_report(row: sqlite3.Row) -> PdfReport:
    return PdfReport(
        id=row["id"],
        pdf_hash=row["pdf_hash"],
        violations=row["violations"],
        failed_checks=row["failed_checks"],
        tagged=bool(row["tagged"]),
        image_only=bool(row["image_only"]),
        text_type=row["text_type"],
        title_set=bool(row["title_set"]),
        language_set=bool(row["language_set"]),
        page_count=row["page_count"],
        has_form=bool(row["has_form"]),
        complex_graphic=bool(row["complex_graphic"]),
        created_at=row["created_at"],
    )


class ReportRepository(BaseRepository):
    def upsert(self, report: PdfReport, overwrite: bool = True) -> int:
        conflict = (
            """
            ON CONFLICT(pdf_hash) DO UPDATE SET
                violations = excluded.violations,
                failed_checks = excluded.failed_checks,
                tagged = excluded.tagged,
                image_only = excluded.image_only,
                text_type = excluded.text_type,
                title_set = excluded.title_set,
                language_set = excluded.language_set,
                page_count = excluded.page_count,
                has_form = excluded.has_form,
                complex_graphic = excluded.complex_graphic
            """
            if overwrite
            else "ON CONFLICT(pdf_hash) DO NOTHING"
        )
        cur = self.conn.execute(
            f"""
            INSERT INTO pdf_report (
                pdf_hash, violations, failed_checks, tagged, image_only,
                text_type, title_set, language_set, page_count, has_form,
                complex_graphic
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            {conflict}
            """,
            (
                report.pdf_hash,
                report.violations,
                report.failed_checks,
                int(report.tagged),
                int(report.image_only),
                report.text_type,
                int(report.title_set),
                int(report.language_set),
                report.page_count,
                int(report.has_form),
                int(report.complex_graphic),
            ),
        )
        if cur.lastrowid:
            return int(cur.lastrowid)
        row = self.conn.execute(
            "SELECT id FROM pdf_report WHERE pdf_hash = ?", (report.pdf_hash,)
        ).fetchone()
        return int(row[0]) if row else 0

    def exists_for_hash(self, file_hash: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM pdf_report WHERE pdf_hash = ?", (file_hash,)
        ).fetchone()
        return row is not None

    def get_by_hash(self, file_hash: str) -> PdfReport | None:
        row = self.conn.execute(
            "SELECT * FROM pdf_report WHERE pdf_hash = ?", (file_hash,)
        ).fetchone()
        return _row_to_report(row) if row else None

    # -- per-rule detail --------------------------------------------------------
    def replace_rules(self, pdf_hash: str, rules: list[ReportRule]) -> int:
        """Replace the stored veraPDF rules for ``pdf_hash``. Returns the count.

        Idempotent across re-verification: existing rows for the hash are cleared
        first so a fresh veraPDF run fully supersedes the old result.
        """
        self.conn.execute("DELETE FROM report_rule WHERE pdf_hash = ?", (pdf_hash,))
        self.conn.executemany(
            """
            INSERT INTO report_rule
                (pdf_hash, clause, test_number, status, failed_checks, specification, description)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    pdf_hash,
                    r.clause,
                    r.test_number,
                    r.status,
                    r.failed_checks,
                    r.specification,
                    r.description,
                )
                for r in rules
            ],
        )
        return len(rules)

    def list_rules(self, pdf_hash: str) -> list[ReportRule]:
        """Return the stored veraPDF rules for ``pdf_hash`` (insertion order)."""
        rows = self.conn.execute(
            """
            SELECT clause, test_number, status, failed_checks, specification, description
            FROM report_rule WHERE pdf_hash = ? ORDER BY id
            """,
            (pdf_hash,),
        ).fetchall()
        return [
            ReportRule(
                clause=r["clause"],
                test_number=r["test_number"],
                status=r["status"],
                failed_checks=r["failed_checks"],
                specification=r["specification"],
                description=r["description"],
            )
            for r in rows
        ]
