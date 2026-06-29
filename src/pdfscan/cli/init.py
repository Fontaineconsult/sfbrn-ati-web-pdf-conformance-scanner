"""`pdfscan init` -- easy-mode setup.

Guides a first-time scan into existence: pick a session name, choose a workspace
folder (all outputs go there), the database is created/migrated, the PDF-verify
tools (Java + veraPDF) are checked -- offering to install veraPDF when it's
missing -- then it waits for you to add the sites to scan. Equivalent to, but
friendlier than, running ``session add --use`` + ``db init`` + ``setup-verapdf``
+ repeated ``site add`` by hand.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import typer

from pdfscan.config import load_sessions
from pdfscan.service import ScannerError, ScannerService

# BOM + zero-width marks Windows stdin piping can inject; built via chr() so this
# source file stays pure ASCII.
_INVISIBLE = {c: None for c in (0xFEFF, 0x200B, 0x200C, 0x200D, 0x2060)}


def _clean(text: str) -> str:
    """Strip surrounding whitespace and any BOM/zero-width marks (Windows stdin
    piping can prepend a U+FEFF, which str.strip() leaves intact)."""
    return text.translate(_INVISIBLE).strip()


def _slug(text: str) -> str:
    """Filesystem-safe folder name derived from a session name."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", _clean(text)).strip("-")
    return cleaned or "session"


def _parse_site(spec: str) -> dict:
    """Parse a ``--site NAME=URL[,URL2]`` value into an add_site spec."""
    name, _, urls = spec.partition("=")
    name = _clean(name)
    seeds = [u.strip() for u in urls.split(",") if u.strip()]
    if not name or not seeds:
        raise typer.BadParameter(f"--site must look like NAME=URL[,URL2] (got '{spec}')")
    return {"name": name, "seeds": seeds}


def _add_sites_interactively(svc: ScannerService) -> int:
    """Prompt for sites until a blank name is entered. Returns the count added."""
    typer.echo("\nAdd sites to scan. Press Enter on an empty name when you're done.")
    count = 0
    while True:
        name = _clean(typer.prompt("  site name", default="", show_default=False))
        if not name:
            break
        seeds_raw = _clean(typer.prompt("  seed URL(s), comma-separated"))
        seeds = [u.strip() for u in seeds_raw.split(",") if u.strip()]
        if not seeds:
            typer.echo("    (skipped: no URL given)")
            continue
        try:
            svc.add_site(name, seeds)
            count += 1
            typer.echo(f"    + added '{name}'")
        except ScannerError as exc:
            typer.echo(f"    ! {exc}")
    return count


def _check_tooling(svc: ScannerService, *, assume_yes: bool) -> None:
    """Verify the PDF-verification dependencies (Java + veraPDF) and offer to
    install veraPDF when it is missing (and Java is present, which veraPDF's own
    installer needs). Crawling needs neither tool, so a missing one is a warning,
    never fatal. The install prompt is skipped in non-interactive runs unless
    ``assume_yes`` is set, so this never blocks a script."""
    doc = svc.doctor()
    java_ok = doc["java"]["ok"]
    vera_ok = doc["verapdf"]["ok"]

    typer.echo("\nChecking PDF-verification tools:")
    typer.echo(
        f"  [OK] Java: {doc['java']['version'] or 'available'}"
        if java_ok
        else "  [X]  Java: not found (a Java 8+ runtime is required)"
    )
    if vera_ok:
        typer.echo(f"  [OK] veraPDF: {doc['verapdf']['version'] or 'available'}")
        return

    typer.echo("  [X]  veraPDF: not installed")
    if not java_ok:
        typer.echo("       veraPDF needs Java to install and run. Install a JRE, then run:")
        typer.echo("         pdfscan setup-verapdf")
        return

    want_install = assume_yes or (
        sys.stdin.isatty() and typer.confirm("  Download and install veraPDF now?", default=True)
    )
    if not want_install:
        typer.echo("       Install later (needed for verify/report): pdfscan setup-verapdf")
        return

    typer.echo("  Installing veraPDF (downloads tens of MB; this can take a minute)...")
    try:
        path = svc.setup_verapdf()
        typer.echo(f"  [OK] veraPDF installed at {path}")
    except RuntimeError as exc:
        typer.echo(f"  [X]  veraPDF install failed: {exc}")
        typer.echo("       Retry later with: pdfscan setup-verapdf")


def _print_next_steps(svc: ScannerService) -> None:
    names = [s["name"] for s in svc.list_sites()]
    typer.echo("\nNext steps:")
    if names:
        for name in names[:5]:
            typer.echo(f"  pdfscan run {name}        # crawl + verify + report")
        if len(names) > 5:
            typer.echo(f"  ... and {len(names) - 5} more")
    else:
        typer.echo("  pdfscan site add <name> --seed <url>")
    typer.echo("\nThe session is active, so plain `pdfscan` commands target this workspace.")
    typer.echo("Switch later with: pdfscan session use <name>")


def init(
    ctx: typer.Context,
    name: str | None = typer.Argument(None, help="Session name (prompted if omitted)."),
    root: Path | None = typer.Option(
        None, "--root", help="Workspace folder for all outputs (prompted if omitted)."
    ),
    label: str | None = typer.Option(None, "--label", help="Human-readable session description."),
    site: list[str] = typer.Option(
        None,
        "--site",
        help="Pre-add a site as NAME=URL[,URL2] (repeatable; skips the interactive prompt).",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Accept the default workspace folder without prompting."
    ),
) -> None:
    """Easy mode: create a session workspace, set up its database, then add sites."""
    name = _clean(name) if name else _clean(typer.prompt("Session name"))
    if not name:
        raise typer.BadParameter("a session name is required")

    registry = load_sessions()
    existing = registry.get(name)
    if existing:
        root_path = existing.root
        if root is not None and root.expanduser() != existing.root:
            typer.echo(
                f"note: session '{name}' already exists; keeping its workspace "
                f"{existing.root} (ignoring --root {root})."
            )
        else:
            typer.echo(f"Reusing existing session '{name}' at {root_path}.")
    elif root is not None:
        root_path = root
    else:
        default_root = Path.cwd() / "scans" / _slug(name)
        root_path = (
            default_root
            if yes
            else Path(typer.prompt("Workspace folder", default=str(default_root)))
        )

    svc = ScannerService(ctx.obj)
    parsed = [_parse_site(s) for s in (site or [])]
    summary = svc.quickstart(name, root_path, label=label, sites=parsed)

    typer.echo(f"\n[ok] Session '{summary['session']}' is active at {summary['root']}")
    typer.echo(
        f"  database : {summary['paths']['database']}  (schema v{summary['schema_version']})"
    )
    typer.echo(f"  exports  : {summary['paths']['exports']}")
    typer.echo(f"  remediation : {summary['paths']['remediation']}")

    _check_tooling(svc, assume_yes=yes)

    if parsed:
        for name_added in summary["sites_added"]:
            typer.echo(f"  + site '{name_added}'")
    else:
        # Only nag about "no sites" when the session truly has none -- re-running
        # init on a populated session and adding nothing new is fine.
        if _add_sites_interactively(svc) == 0 and not svc.list_sites():
            typer.echo("  (no sites yet -- add later with: pdfscan site add <name> --seed <url>)")

    _print_next_steps(svc)
