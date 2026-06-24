"""Ordered registry of resolvers."""

from __future__ import annotations

from pdfscan.resolvers.base import Resolver, ResolverResult


class ResolverRegistry:
    """Holds resolvers in registration order and dispatches URLs to the first match."""

    def __init__(self) -> None:
        self._resolvers: list[Resolver] = []

    def register(self, resolver: Resolver) -> None:
        """Append ``resolver`` to the registry (registration order is match order)."""
        self._resolvers.append(resolver)

    def match(self, url: str) -> Resolver | None:
        """Return the first registered resolver whose ``matches`` is True, else ``None``."""
        for resolver in self._resolvers:
            if resolver.matches(url):
                return resolver
        return None

    def resolve(self, url: str, html: str | None = None) -> ResolverResult:
        """Delegate to the matching resolver, or return an error result if none matches."""
        resolver = self.match(url)
        if resolver is None:
            return ResolverResult([], error="no resolver")
        return resolver.resolve(url, html)

    def names(self) -> list[str]:
        """Names of the registered resolvers, in registration order."""
        return [r.name for r in self._resolvers]
