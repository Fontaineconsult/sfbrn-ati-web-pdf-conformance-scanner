"""Thin data-access layer: one repository per aggregate."""

from pdfscan.db.repositories.failures import FailureRepository
from pdfscan.db.repositories.owners import PersonRepository, SiteOwnerRepository
from pdfscan.db.repositories.pdfs import PdfRepository
from pdfscan.db.repositories.reports import ReportRepository
from pdfscan.db.repositories.sites import SiteRepository

__all__ = [
    "SiteRepository",
    "PdfRepository",
    "ReportRepository",
    "FailureRepository",
    "SiteOwnerRepository",
    "PersonRepository",
]
