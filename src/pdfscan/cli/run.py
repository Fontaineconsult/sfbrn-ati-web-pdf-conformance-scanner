"""`pdfscan run <site>` - full pipeline: crawl -> verify -> archive -> export."""

from __future__ import annotations

import json

import typer

from pdfscan.config import Settings
from pdfscan.service import ScannerService


def _settings(ctx: typer.Context) -> Settings:
    return ctx.obj


def run(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Configured site name."),
    no_crawl: bool = typer.Option(False, "--no-crawl"),
    no_verify: bool = typer.Option(False, "--no-verify"),
    no_archive: bool = typer.Option(False, "--no-archive"),
    do_404: bool = typer.Option(False, "--check-404", help="Also refresh 404 status."),
    export: list[str] = typer.Option(None, "--export", help="csv|json|excel (repeatable)."),
    depth: int | None = typer.Option(None, "--depth"),
    render: bool | None = typer.Option(None, "--render/--no-render"),
    include_offsite_pdfs: bool | None = typer.Option(
        None, "--include-offsite-pdfs/--no-include-offsite-pdfs"
    ),
    max_pages: int | None = typer.Option(None, "--max-pages"),
    timeout_s: int | None = typer.Option(None, "--timeout"),
    limit: int | None = typer.Option(None, "--limit", help="Max PDFs to verify."),
) -> None:
    """Run the end-to-end pipeline for a site."""
    settings = _settings(ctx)
    svc = ScannerService(settings)

    overrides: dict = {}
    for key, val in (
        ("max_depth", depth),
        ("render_js", render),
        ("include_external_pdfs", include_offsite_pdfs),
        ("max_pages", max_pages),
        ("timeout_s", timeout_s),
    ):
        if val is not None:
            overrides[key] = val

    bad = [f for f in (export or []) if f not in {"csv", "json", "excel"}]
    if bad:
        typer.echo(f"Invalid --export value(s): {bad}")
        raise typer.Exit(code=1)

    result = svc.run(
        name,
        do_crawl=not no_crawl,
        do_verify=not no_verify,
        do_archive=not no_archive,
        do_404=do_404,
        verify_limit=limit,
        overrides=overrides or None,
        exports=list(export) if export else None,
    )
    typer.echo(json.dumps(result, indent=2))
