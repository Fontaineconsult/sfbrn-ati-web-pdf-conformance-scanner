"""Small logging helpers shared across the package."""

from __future__ import annotations

import logging

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_configured = False


def get_logger(name: str = "pdfscan") -> logging.Logger:
    """Return a named logger (no side effects on the root configuration)."""
    return logging.getLogger(name)


def configure_logging(level: str = "INFO") -> None:
    """Configure root logging once (idempotent)."""
    global _configured
    if _configured:
        return
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), format=_FORMAT)
    _configured = True
