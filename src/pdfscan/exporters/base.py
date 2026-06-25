"""Shared row collection for exporters."""

from __future__ import annotations

from pdfscan.classify import classify_rows, load_classification_profile
from pdfscan.config import Settings, load_ignore_profiles
from pdfscan.db import session
from pdfscan.db.repositories import PdfRepository, SiteRepository

# Stable column order for tabular exports.
COLUMNS = [
    "site",
    "owner",
    "responsible",
    "pdf_url",
    "parent_url",
    "scanned_at",
    "offsite",
    "via_resolver",
    "archived",
    "removed",
    "pdf_404",
    "parent_404",
    "file_hash",
    "violations",
    "failed_checks",
    "tagged",
    "image_only",
    "text_type",
    "title_set",
    "language_set",
    "page_count",
    "has_form",
    "complex_graphic",
    "classification",
    "classification_reason",
    "local_path",
]


def collect_rows(settings: Settings, site_name: str | None = None) -> list[dict]:
    """Return flat joined rows (pdf_files + pdf_report) for a site or all sites.

    Each row carries the read-time remediation ``classification`` and its
    ``classification_reason`` (good_to_go / fit_for_automated_tagging /
    needs_manual_remediation), derived from the ignore + classification policies.
    """
    ignore = load_ignore_profiles(
        settings.resolve_path(
            settings.get("verapdf.ignore_profiles") or "config/ignore_profiles.yaml"
        )
    )
    profile = load_classification_profile(
        settings.resolve_path(
            settings.get("classification.profile") or "config/classification.yaml"
        )
    )
    with session(settings.db_path) as conn:
        site_id = None
        if site_name:
            site = SiteRepository(conn).get_by_name(site_name)
            if site is None:
                raise ValueError(f"No such site '{site_name}'")
            site_id = site.id
        rows = PdfRepository(conn).export_rows(site_id)
        cls = classify_rows(conn, rows, ignore, profile)

    out: list[dict] = []
    for row in rows:
        rec = {col: row.get(col) for col in COLUMNS}  # stable column set/order
        c = cls[row["pdf_url"]]
        rec["classification"] = c.label.value
        rec["classification_reason"] = c.reason
        out.append(rec)
    return out
