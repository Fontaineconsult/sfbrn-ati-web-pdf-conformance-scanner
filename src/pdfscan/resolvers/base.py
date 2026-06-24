"""Resolver protocol and result type."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ResolverResult:
    """Outcome of resolving a share/embed URL into direct PDF download URLs."""

    pdf_urls: list[str] = field(default_factory=list)
    filename: str | None = None
    error: str | None = None


@runtime_checkable
class Resolver(Protocol):
    """A handler that turns a third-party share URL into direct PDF URL(s)."""

    name: str

    def matches(self, url: str) -> bool:
        """True if this resolver knows how to handle ``url``."""
        ...

    def resolve(self, url: str, html: str | None = None) -> ResolverResult:
        """Resolve ``url`` (optionally given pre-fetched ``html``) to direct PDF URLs."""
        ...
