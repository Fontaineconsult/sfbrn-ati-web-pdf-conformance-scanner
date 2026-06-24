"""`pdfscan status <site>` summary and `pdfscan check-404 <site>`."""

from __future__ import annotations

import typer

from pdfscan.config import Settings
from pdfscan.db import session
from pdfscan.db.repositories import FailureRepository, PdfRepository, SiteRepository


def _settings(ctx: typer.Context) -> Settings:
    return ctx.obj


def status(ctx: typer.Context, name: str) -> None:
    """Show a coverage/accessibility summary for a site."""
    settings = _settings(ctx)
    with session(settings.db_path) as conn:
        site = SiteRepository(conn).get_by_name(name)
        if not site:
            typer.echo(f"No such site '{name}'.")
            raise typer.Exit(code=1)
        rows = PdfRepository(conn).export_rows(site.id)
        n_fail = FailureRepository(conn).count_by_site(site.id)

    total = len(rows)
    verified = [r for r in rows if r["violations"] is not None]
    untagged = sum(1 for r in verified if not r["tagged"])
    image_only = sum(1 for r in verified if r["image_only"])
    with_viol = sum(1 for r in verified if (r["violations"] or 0) > 0)
    clean = sum(1 for r in verified if (r["violations"] or 0) == 0 and r["tagged"])

    typer.echo(f"Site '{name}':")
    typer.echo(f"  PDFs discovered : {total}")
    typer.echo(f"  offsite         : {sum(1 for r in rows if r['offsite'])}")
    typer.echo(f"  via resolver    : {sum(1 for r in rows if r['via_resolver'])}")
    typer.echo(f"  archived        : {sum(1 for r in rows if r['archived'])}")
    typer.echo(f"  verified        : {len(verified)}")
    typer.echo(f"    untagged      : {untagged}")
    typer.echo(f"    image-only    : {image_only}")
    typer.echo(f"    with violations: {with_viol}")
    typer.echo(f"    likely passing: {clean}")
    typer.echo(f"  failures        : {n_fail}")


def check_404(ctx: typer.Context, name: str) -> None:
    """Refresh 404 status for a site's PDFs and parent pages."""
    settings = _settings(ctx)
    from pdfscan.pipeline.status import refresh_404

    with session(settings.db_path) as conn:
        site = SiteRepository(conn).get_by_name(name)
        if not site:
            typer.echo(f"No such site '{name}'.")
            raise typer.Exit(code=1)
        stats = refresh_404(conn, site.id, settings)
    typer.echo(
        f"Checked {stats['checked']}: pdf_404={stats['pdf_404']} parent_404={stats['parent_404']}"
    )
