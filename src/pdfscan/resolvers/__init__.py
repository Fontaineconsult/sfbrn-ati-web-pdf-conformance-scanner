"""Resolver subsystem: protocol, registry, and the default resolver set."""

from __future__ import annotations

from pdfscan.resolvers.base import Resolver, ResolverResult
from pdfscan.resolvers.box import BoxResolver
from pdfscan.resolvers.registry import ResolverRegistry

# Name -> resolver class for the known resolvers.
_KNOWN: dict[str, type] = {"box": BoxResolver}

__all__ = [
    "Resolver",
    "ResolverResult",
    "ResolverRegistry",
    "BoxResolver",
    "default_registry",
]


def default_registry(enabled: list[str] | None = None) -> ResolverRegistry:
    """Build a registry of the known resolvers, filtered by ``enabled`` (None = all)."""
    registry = ResolverRegistry()
    for name, cls in _KNOWN.items():
        if enabled is None or name in enabled:
            registry.register(cls())
    return registry
