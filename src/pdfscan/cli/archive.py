"""`pdfscan archive apply <site>` and `pdfscan archive test <url|--from-file>`."""

from __future__ import annotations

from pathlib import Path

import typer

from pdfscan.config import Settings
from pdfscan.db import session
from pdfscan.db.repositories import SiteRepository
from pdfscan.pipeline.archive import apply_archive_flags, explain, rules_from_settings

archive_app = typer.Typer(help="Archive heuristics (flag old/legacy PDFs).", no_args_is_help=True)


def _settings(ctx: typer.Context) -> Settings:
    return ctx.obj


@archive_app.command("apply")
def archive_apply(ctx: typer.Context, name: str) -> None:
    """Flag a site's archived-looking PDFs (sets pdf_files.archived)."""
    settings = _settings(ctx)
    rules = rules_from_settings(settings)
    with session(settings.db_path) as conn:
        site = SiteRepository(conn).get_by_name(name)
        if not site:
            typer.echo(f"No such site '{name}'.")
            raise typer.Exit(code=1)
        flagged = apply_archive_flags(conn, site.id, rules)
    typer.echo(f"Flagged {flagged} archived PDF(s) for '{name}'.")


@archive_app.command("test")
def archive_test(
    ctx: typer.Context,
    url: str | None = typer.Argument(None, help="A single URL to test."),
    from_file: Path | None = typer.Option(None, "--from-file", help="File of URLs (one per line)."),
) -> None:
    """Dry-run the archive rules against URLs without scanning."""
    settings = _settings(ctx)
    rules = rules_from_settings(settings)
    urls: list[str] = []
    if url:
        urls.append(url)
    if from_file:
        urls += [ln.strip() for ln in Path(from_file).read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not urls:
        typer.echo("Provide a URL argument or --from-file.")
        raise typer.Exit(code=1)
    for u in urls:
        reason = explain(u, rules)
        label = "ARCHIVED" if reason else "active  "
        typer.echo(f"{label}  {u}" + (f"   <- {reason}" if reason else ""))
