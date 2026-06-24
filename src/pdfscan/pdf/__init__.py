"""PDF analysis subpackage: hashing, veraPDF parsing, and structural analysis."""

from pdfscan.pdf.analyze import PdfAnalysis, analyze_pdf
from pdfscan.pdf.hashing import sha256_bytes, sha256_file
from pdfscan.pdf.verapdf import VeraSummary, parse_verapdf, run_verapdf

__all__ = [
    "sha256_file",
    "sha256_bytes",
    "VeraSummary",
    "parse_verapdf",
    "run_verapdf",
    "PdfAnalysis",
    "analyze_pdf",
]
