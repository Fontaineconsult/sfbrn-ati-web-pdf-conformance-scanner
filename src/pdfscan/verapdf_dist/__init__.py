"""Bundled veraPDF distribution helpers: locate, resolve, and headless-install.

Public API (depended on by the CLI and tool-check helpers):

* :func:`installed_verapdf_path` -- the installed launcher under ``verapdf_dir``.
* :func:`resolve_verapdf` -- locate veraPDF honouring config precedence.
* :func:`ensure_verapdf` -- ensure a runnable veraPDF, installing if needed.
"""

from __future__ import annotations

from pdfscan.verapdf_dist.installer import (
    ensure_verapdf,
    installed_verapdf_path,
    resolve_verapdf,
)

__all__ = [
    "installed_verapdf_path",
    "resolve_verapdf",
    "ensure_verapdf",
]
