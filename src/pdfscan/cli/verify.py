"""`pdfscan verify <site>` - download discovered PDFs and run veraPDF + analysis."""

from __future__ import annotations

import typer

from pdfscan.config import Settings, load_ignore_profiles
from pdfscan.db import session
from pdfscan.db.repositories import PdfRepository, SiteRepository


def _settings(ctx: typer.Context) -> Settings:
    return ctx.obj


def verify(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Configured site name."),
    refresh: bool = typer.Option(False, "--refresh", help="Re-verify already-reported PDFs too."),
    limit: int | None = typer.Option(None, "--limit", help="Only verify the first N PDFs."),
    save: bool = typer.Option(True, "--save/--no-save", help="Save copies for remediation."),
) -> None:
    """Verify a site's PDFs for accessibility."""
    settings = _settings(ctx)

    from pdfscan.verapdf_dist import resolve_verapdf  # lazy: only needed here

    verapdf_cmd = resolve_verapdf(settings)
    if not verapdf_cmd:
        typer.echo("veraPDF not found. Install it with: pdfscan setup-verapdf")
        raise typer.Exit(code=1)

    ip_path = settings.resolve_path(
        settings.get("verapdf.ignore_profiles") or "config/ignore_profiles.yaml"
    )
    ignore = load_ignore_profiles(ip_path)

    from pdfscan.pdf.verify import verify_pdf

    with session(settings.db_path) as conn:
        site = SiteRepository(conn).get_by_name(name)
        if not site:
            typer.echo(f"No such site '{name}'.")
            raise typer.Exit(code=1)
        pdfs = PdfRepository(conn)
        rows = pdfs.list_by_site(site.id) if refresh else pdfs.list_unverified(site.id)
        if limit:
            rows = rows[:limit]
        template = site.config.storage_template or str(settings.get("storage.template"))

        typer.echo(f"Verifying {len(rows)} PDF(s) for '{name}' ...")
        counts = {"verified": 0, "reused": 0, "failed": 0}
        for i, pdf in enumerate(rows, 1):
            outcome = verify_pdf(
                conn, pdf, settings, verapdf_cmd, ignore,
                site_name=site.name, storage_template=template, save=save,
            )
            counts[outcome.status] = counts.get(outcome.status, 0) + 1
            conn.commit()
            if i % 10 == 0 or i == len(rows):
                typer.echo(f"  {i}/{len(rows)} (verified={counts['verified']} "
                           f"reused={counts['reused']} failed={counts['failed']})")

    typer.echo(
        f"Done: verified={counts['verified']} reused={counts['reused']} failed={counts['failed']}"
    )
