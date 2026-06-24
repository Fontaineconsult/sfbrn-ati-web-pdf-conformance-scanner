"""Remediation storage: lay downloaded PDFs out in a per-site folder structure."""

from pdfscan.storage.layout import render_storage_path, save_pdf

__all__ = ["render_storage_path", "save_pdf"]
