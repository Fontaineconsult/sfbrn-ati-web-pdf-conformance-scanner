"""Best-effort availability checks for external tools (Java, veraPDF, Chromium).

These helpers never raise: each returns a simple status so the ``pdfscan doctor``
command can print a checklist regardless of what is or isn't installed.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from pdfscan.verapdf_dist import resolve_verapdf

if TYPE_CHECKING:
    from pdfscan.config import Settings

__all__ = [
    "java_available",
    "verapdf_available",
    "playwright_chromium_installed",
]


def java_available() -> tuple[bool, str | None]:
    """Return ``(ok, version_line)`` for the Java runtime.

    ``java -version`` prints to *stderr*, so we read both streams. Returns
    ``(False, None)`` if java is missing or the call fails.
    """
    try:
        proc = subprocess.run(
            ["java", "-version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False, None

    output = (proc.stderr or "") + (proc.stdout or "")
    version_line: str | None = None
    for line in output.splitlines():
        if line.strip():
            version_line = line.strip()
            break

    return proc.returncode == 0, version_line


def verapdf_available(settings: Settings) -> tuple[bool, str | None]:
    """Return ``(ok, version)`` for veraPDF, resolved via :func:`resolve_verapdf`.

    Resolves a veraPDF executable and runs ``<verapdf> --version``. Returns
    ``(False, None)`` when no executable is found or the call fails.
    """
    exe = resolve_verapdf(settings)
    if not exe:
        return False, None

    try:
        proc = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            timeout=int(settings.get("verapdf.timeout", 180)),
        )
    except (OSError, subprocess.SubprocessError):
        return False, None

    if proc.returncode != 0:
        return False, None

    # veraPDF prints several lines (version, build date, licence); the first
    # non-empty line (e.g. "veraPDF 1.30.2") is the useful one for a checklist.
    raw = (proc.stdout or proc.stderr or "").strip()
    version = next((ln.strip() for ln in raw.splitlines() if ln.strip()), None)
    return True, version


def playwright_chromium_installed() -> bool:
    """Best-effort check for an installed Playwright Chromium browser.

    Looks under the Playwright browsers directory (``PLAYWRIGHT_BROWSERS_PATH``
    or the per-OS default) for a ``chromium*`` folder. Never raises.
    """
    try:
        env_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
        candidates: list[Path] = []
        if env_path and env_path != "0":
            candidates.append(Path(env_path))
        else:
            # Per-OS defaults used by Playwright's browser fetcher.
            if os.name == "nt":
                local = os.environ.get("LOCALAPPDATA")
                if local:
                    candidates.append(Path(local) / "ms-playwright")
            else:
                home = Path.home()
                candidates.append(home / ".cache" / "ms-playwright")
                candidates.append(
                    home / "Library" / "Caches" / "ms-playwright"
                )

        for base in candidates:
            try:
                if base.is_dir() and any(
                    child.is_dir() and child.name.lower().startswith("chromium")
                    for child in base.iterdir()
                ):
                    return True
            except OSError:
                continue
        return False
    except Exception:
        return False
