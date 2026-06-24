"""Domain models (plain dataclasses) shared across all layers."""

from pdfscan.models.failure import Failure
from pdfscan.models.pdf import DiscoveredPdf, PdfFile
from pdfscan.models.report import PdfReport
from pdfscan.models.site import Site, SiteConfig

__all__ = [
    "Site",
    "SiteConfig",
    "DiscoveredPdf",
    "PdfFile",
    "PdfReport",
    "Failure",
]
