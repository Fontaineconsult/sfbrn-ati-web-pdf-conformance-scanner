"""`pdfscan site ...` commands (DB-backed site management)."""

from __future__ import annotations

import typer

from pdfscan.config import Settings
from pdfscan.db import session
from pdfscan.db.repositories import PdfRepository, SiteRepository
from pdfscan.models import Site, SiteConfig
from pdfscan.utils.urls import ensure_scheme, host_of

site_app = typer.Typer(help="Manage sites to scan.", no_args_is_help=True)


def _settings(ctx: typer.Context) -> Settings:
    return ctx.obj


@site_app.command("add")
def site_add(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Short site name (unique)."),
    seed: list[str] = typer.Option(..., "--seed", "-s", help="Seed URL (repeatable)."),
    host: list[str] = typer.Option(
        None, "--host", help="Allowed host(s); defaults to the seed hosts."
    ),
    scope: str = typer.Option("host", "--scope", help="host | subdomain | domain | path"),
    depth: int = typer.Option(0, "--depth", help="Max crawl depth (0 = unlimited)."),
    render: bool = typer.Option(False, "--render/--no-render", help="Render JS (Playwright)."),
    obey_robots: bool = typer.Option(False, "--obey-robots/--no-obey-robots"),
    delay: float | None = typer.Option(None, "--delay", help="Download delay (s)."),
    concurrency: int | None = typer.Option(None, "--concurrency"),
    resolver: list[str] = typer.Option(None, "--resolver", help="Enable resolver (repeatable)."),
    include_offsite_pdfs: bool = typer.Option(
        False, "--include-offsite-pdfs/--no-include-offsite-pdfs"
    ),
    path_prefix: str | None = typer.Option(None, "--path-prefix", help="For scope=path."),
    storage_template: str | None = typer.Option(None, "--storage-template"),
    notes: str | None = typer.Option(None, "--notes"),
) -> None:
    """Add or update a site."""
    if scope not in {"host", "subdomain", "domain", "path"}:
        raise typer.BadParameter("scope must be host|subdomain|domain|path")
    seeds = [ensure_scheme(s) for s in seed if s and s.strip()]
    if not seeds:
        raise typer.BadParameter("at least one non-empty --seed URL is required")
    allowed = list(host) if host else [h for h in (host_of(s) for s in seeds) if h]
    cfg = SiteConfig(
        seeds=list(seeds),
        allowed_hosts=allowed,
        scope=scope,
        max_depth=depth,
        render_js=render,
        obey_robots=obey_robots,
        download_delay=delay,
        concurrency=concurrency,
        resolvers=list(resolver) if resolver else None,
        include_external_pdfs=include_offsite_pdfs,
        storage_template=storage_template,
        path_prefix=path_prefix,
    )
    settings = _settings(ctx)
    with session(settings.db_path) as conn:
        sid = SiteRepository(conn).upsert(Site(id=None, name=name, config=cfg, notes=notes))
    typer.echo(f"Saved site '{name}' (id={sid}); scope={scope} depth={depth} seeds={seeds}")


@site_app.command("list")
def site_list(ctx: typer.Context) -> None:
    """List configured sites."""
    settings = _settings(ctx)
    with session(settings.db_path) as conn:
        sites = SiteRepository(conn).list()
        pdfs = PdfRepository(conn)
        if not sites:
            typer.echo("No sites configured. Add one with: pdfscan site add <name> --seed <url>")
            return
        for s in sites:
            n = len(pdfs.list_by_site(s.id))
            flag = "" if s.enabled else " (disabled)"
            typer.echo(f"{s.name}{flag}: scope={s.config.scope} depth={s.config.max_depth} pdfs={n}")


@site_app.command("show")
def site_show(ctx: typer.Context, name: str) -> None:
    """Show a site's full configuration."""
    settings = _settings(ctx)
    with session(settings.db_path) as conn:
        site = SiteRepository(conn).get_by_name(name)
    if not site:
        raise typer.Exit(code=1)
    typer.echo(f"name: {site.name}")
    typer.echo(f"enabled: {site.enabled}")
    typer.echo(f"notes: {site.notes or ''}")
    typer.echo(f"config: {site.config.to_json()}")


@site_app.command("remove")
def site_remove(ctx: typer.Context, name: str) -> None:
    """Remove a site and its discovered PDFs."""
    settings = _settings(ctx)
    with session(settings.db_path) as conn:
        ok = SiteRepository(conn).remove(name)
    typer.echo(f"Removed '{name}'" if ok else f"No such site '{name}'")
