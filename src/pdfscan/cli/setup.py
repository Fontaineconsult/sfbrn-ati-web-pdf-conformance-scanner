"""`pdfscan setup-verapdf` and `pdfscan doctor` command implementations.

These are plain Typer-command functions; the application wires them onto the
top-level app (this module does not edit ``cli/app.py``).
"""

from __future__ import annotations

import typer

from pdfscan.config import Settings
from pdfscan.utils.tools_check import (
    java_available,
    playwright_chromium_installed,
    verapdf_available,
)
from pdfscan.verapdf_dist import ensure_verapdf

# If a developer has already fetched the installer zip, reuse it instead of
# re-downloading. Resolved relative to the settings base_dir.
_CACHED_INSTALLER = ".scratch/verapdf-installer.zip"


def _settings(ctx: typer.Context) -> Settings:
    return ctx.obj


def setup_verapdf(
    ctx: typer.Context,
    force: bool = typer.Option(False, "--force", help="Reinstall even if veraPDF is present."),
) -> None:
    """Download and headlessly install the bundled veraPDF, then print its path."""
    settings = _settings(ctx)

    cached = settings.resolve_path(_CACHED_INSTALLER)
    installer_zip = str(cached) if cached.is_file() else None

    try:
        path = ensure_verapdf(settings, force=force, installer_zip=installer_zip)
    except RuntimeError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1) from exc

    typer.echo(f"veraPDF ready at: {path}")


def doctor(ctx: typer.Context) -> None:
    """Check Java, veraPDF, and Playwright/Chromium availability."""
    settings = _settings(ctx)

    # ASCII markers: the Windows console (cp1252) cannot encode U+2713/U+2717,
    # and typer.echo would raise UnicodeEncodeError there.
    ok_mark = "[OK]"
    bad_mark = "[X] "

    java_ok, java_version = java_available()
    if java_ok:
        typer.echo(f"{ok_mark} Java: {java_version or 'available'}")
    else:
        typer.echo(f"{bad_mark} Java: not found (install a Java 8+ runtime)")

    vera_ok, vera_version = verapdf_available(settings)
    if vera_ok:
        typer.echo(f"{ok_mark} veraPDF: {vera_version or 'available'}")
    else:
        typer.echo(f"{bad_mark} veraPDF: not found -- run `pdfscan setup-verapdf`")

    chromium_ok = playwright_chromium_installed()
    if chromium_ok:
        typer.echo(f"{ok_mark} Playwright Chromium: installed")
    else:
        typer.echo(
            f"{bad_mark} Playwright Chromium: not found "
            "(run `playwright install chromium` for JS-rendered crawls)"
        )
