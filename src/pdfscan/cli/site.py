"""`pdfscan site ...` commands (DB-backed site management)."""

from __future__ import annotations

import typer

from pdfscan.config import Settings
from pdfscan.db import session
from pdfscan.db.repositories import PdfRepository, SiteOwnerRepository, SiteRepository
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
    owner: str | None = typer.Option(None, "--owner", help="Owner key (responsible org group)."),
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
        owner_msg = ""
        if owner:
            o = SiteOwnerRepository(conn).get_by_key(owner)
            if o is None:
                owner_msg = f"; warning: no such owner '{owner}' (saved without owner)"
            else:
                SiteRepository(conn).set_owner(name, o.id)
                owner_msg = f"; owner={owner}"
    typer.echo(
        f"Saved site '{name}' (id={sid}); scope={scope} depth={depth} seeds={seeds}{owner_msg}"
    )


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
        owner = (
            SiteOwnerRepository(conn).get_by_id(site.owner_id)
            if site and site.owner_id
            else None
        )
    if not site:
        raise typer.Exit(code=1)
    typer.echo(f"name: {site.name}")
    typer.echo(f"enabled: {site.enabled}")
    typer.echo(f"owner: {owner.key if owner else '-'}")
    typer.echo(f"notes: {site.notes or ''}")
    typer.echo(f"config: {site.config.to_json()}")


@site_app.command("set-owner")
def site_set_owner(
    ctx: typer.Context,
    name: str,
    owner_key: str = typer.Argument(None, help="Owner key to assign (omit with --clear)."),
    clear: bool = typer.Option(False, "--clear", help="Remove the site's owner."),
) -> None:
    """Assign (or --clear) the owner org responsible for a site."""
    settings = _settings(ctx)
    if not clear and not owner_key:
        typer.echo("Provide an owner key or --clear.")
        raise typer.Exit(code=1)
    with session(settings.db_path) as conn:
        owner_id = None
        if not clear:
            owner = SiteOwnerRepository(conn).get_by_key(owner_key)
            if owner is None:
                typer.echo(f"No such owner '{owner_key}'.")
                raise typer.Exit(code=1)
            owner_id = owner.id
        if not SiteRepository(conn).set_owner(name, owner_id):
            typer.echo(f"No such site '{name}'.")
            raise typer.Exit(code=1)
    typer.echo(f"Set owner of '{name}' to {'(cleared)' if clear else owner_key}")


@site_app.command("remove")
def site_remove(ctx: typer.Context, name: str) -> None:
    """Remove a site and its discovered PDFs."""
    settings = _settings(ctx)
    with session(settings.db_path) as conn:
        ok = SiteRepository(conn).remove(name)
    typer.echo(f"Removed '{name}'" if ok else f"No such site '{name}'")
