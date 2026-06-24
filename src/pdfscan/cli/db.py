"""`pdfscan db ...` commands."""

from __future__ import annotations

import typer

from pdfscan.config import Settings
from pdfscan.db import migrate, session

db_app = typer.Typer(help="Database management.", no_args_is_help=True)


def _settings(ctx: typer.Context) -> Settings:
    return ctx.obj


@db_app.command("init")
def db_init(ctx: typer.Context) -> None:
    """Create the SQLite database and schema (idempotent)."""
    settings = _settings(ctx)
    with session(
        settings.db_path,
        wal=bool(settings.get("database.wal", True)),
        busy_timeout_ms=int(settings.get("database.busy_timeout_ms", 30000)),
    ) as conn:
        version = migrate(conn)
    typer.echo(f"Initialized database at {settings.db_path} (schema v{version})")


@db_app.command("migrate")
def db_migrate(ctx: typer.Context) -> None:
    """Apply any pending schema migrations."""
    settings = _settings(ctx)
    with session(settings.db_path) as conn:
        version = migrate(conn)
    typer.echo(f"Database is at schema v{version}")


@db_app.command("vacuum")
def db_vacuum(ctx: typer.Context) -> None:
    """Compact the database file."""
    settings = _settings(ctx)
    with session(settings.db_path) as conn:
        conn.execute("VACUUM")
    typer.echo("VACUUM complete")
