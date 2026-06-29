"""`pdfscan session ...` commands: named, isolated output workspaces.

A session bundles a scan's outputs (database, exports, saved PDFs, scratch) under
one root, so different scans never collide. Select one per run with
``--session <name>`` / ``--session-root <dir>``, set a default with
``session use``, or point the env at one with ``PDFSCAN_SESSION``. See
:mod:`pdfscan.config.sessions` for the resolution rules.
"""

from __future__ import annotations

from pathlib import Path

import typer

from pdfscan.config import SessionError, load_sessions, load_settings

session_app = typer.Typer(
    help="Manage scan sessions (named, isolated output workspaces).",
    no_args_is_help=True,
)


def _fail(message: str) -> None:
    typer.echo(f"Error: {message}")
    raise typer.Exit(code=1)


@session_app.command("add")
def session_add(
    name: str = typer.Argument(..., help="Session name (e.g. a client or audit label)."),
    root: Path = typer.Argument(..., help="Workspace folder; all outputs go under here."),
    label: str | None = typer.Option(None, "--label", help="Human-readable description."),
    notes: str | None = typer.Option(None, "--notes"),
    use: bool = typer.Option(False, "--use/--no-use", help="Also make it the active session."),
) -> None:
    """Register (or update) a session and create its workspace folder."""
    registry = load_sessions()
    try:
        record = registry.add(name, root, label=label, notes=notes, activate=use)
    except SessionError as exc:
        _fail(str(exc))
    registry.save()
    record.root.mkdir(parents=True, exist_ok=True)
    suffix = " (now active)" if use else ""
    typer.echo(f"Registered session '{record.name}' -> {record.root}{suffix}")


@session_app.command("list")
def session_list() -> None:
    """List registered sessions; the active one is marked with '*'."""
    registry = load_sessions()
    sessions = registry.list()
    if not sessions:
        typer.echo("No sessions. Add one with: pdfscan session add <name> <root>")
        return
    for record in sessions:
        marker = "*" if registry.active == record.name else " "
        label = f"  ({record.label})" if record.label else ""
        typer.echo(f"{marker} {record.name}: {record.root}{label}")
    if not registry.active:
        typer.echo("\n(no active session -- outputs default to the project root)")


@session_app.command("use")
def session_use(
    name: str | None = typer.Argument(None, help="Session to activate (omit with --clear)."),
    clear: bool = typer.Option(False, "--clear", help="Clear the active session."),
) -> None:
    """Set the default session for subsequent commands (or clear it)."""
    registry = load_sessions()
    if clear:
        registry.use(None)
        registry.save()
        typer.echo("Cleared active session (outputs default to the project root).")
        return
    if not name:
        _fail("provide a session name, or pass --clear to deactivate.")
    try:
        registry.use(name)
    except SessionError as exc:
        _fail(str(exc))
    registry.save()
    typer.echo(f"Active session: {name}")


@session_app.command("show")
def session_show(
    name: str | None = typer.Argument(None, help="Session to inspect (default: the active one)."),
) -> None:
    """Show a session's details and where each output will be written."""
    registry = load_sessions()
    target = name or registry.active
    if not target:
        _fail("no active session. Select one with: pdfscan session use <name>")
    record = registry.get(target)
    if not record:
        _fail(f"no such session '{target}'.")
    active = " (active)" if registry.active == record.name else ""
    typer.echo(f"session : {record.name}{active}")
    if record.label:
        typer.echo(f"label   : {record.label}")
    if record.notes:
        typer.echo(f"notes   : {record.notes}")
    if record.created_at:
        typer.echo(f"created : {record.created_at}")
    typer.echo(f"root    : {record.root}")
    resolved = load_settings(session=record.name).output_paths()
    for key in ("database", "exports", "remediation", "scratch"):
        typer.echo(f"{key:8}: {resolved[key]}")


@session_app.command("remove")
def session_remove(
    name: str = typer.Argument(..., help="Session to unregister (files on disk are left alone)."),
) -> None:
    """Unregister a session. The workspace folder and its files are not deleted."""
    registry = load_sessions()
    removed = registry.remove(name)
    registry.save()
    typer.echo(f"Removed session '{name}'" if removed else f"No such session '{name}'")
