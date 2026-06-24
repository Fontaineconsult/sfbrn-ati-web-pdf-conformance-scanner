"""`pdfscan crawl <site>` - discover PDFs for a configured site."""

from __future__ import annotations

import typer

from pdfscan.config import Settings
from pdfscan.db import session
from pdfscan.db.repositories import SiteRepository


def _settings(ctx: typer.Context) -> Settings:
    return ctx.obj


def crawl(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Configured site name."),
    render: bool | None = typer.Option(None, "--render/--no-render"),
    obey_robots: bool | None = typer.Option(None, "--obey-robots/--no-obey-robots"),
    delay: float | None = typer.Option(None, "--delay"),
    concurrency: int | None = typer.Option(None, "--concurrency"),
    depth: int | None = typer.Option(None, "--depth"),
    include_offsite_pdfs: bool | None = typer.Option(
        None, "--include-offsite-pdfs/--no-include-offsite-pdfs"
    ),
    max_pages: int | None = typer.Option(None, "--max-pages", help="Safety cap on pages."),
    timeout_s: int | None = typer.Option(None, "--timeout", help="Stop after N seconds."),
) -> None:
    """Crawl a site for PDFs (overrides apply to this run only)."""
    settings = _settings(ctx)
    with session(settings.db_path) as conn:
        site = SiteRepository(conn).get_by_name(name)
    if not site:
        typer.echo(f"No such site '{name}'. Add it with: pdfscan site add {name} --seed <url>")
        raise typer.Exit(code=1)

    overrides: dict = {}
    if render is not None:
        overrides["render_js"] = render
    if obey_robots is not None:
        overrides["obey_robots"] = obey_robots
    if delay is not None:
        overrides["download_delay"] = delay
    if concurrency is not None:
        overrides["concurrency"] = concurrency
    if depth is not None:
        overrides["max_depth"] = depth
    if include_offsite_pdfs is not None:
        overrides["include_external_pdfs"] = include_offsite_pdfs
    if max_pages is not None:
        overrides["max_pages"] = max_pages
    if timeout_s is not None:
        overrides["timeout_s"] = timeout_s

    # Import here so Scrapy/Twisted only load when actually crawling.
    from pdfscan.scraper.runner import crawl_site

    typer.echo(f"Crawling '{name}' ...")
    stats = crawl_site(site, settings, run_overrides=overrides)
    typer.echo(f"Done: {stats['new']} new PDF rows ({stats['total']} total for '{name}').")
