"""`pdfscan owner ...` commands (org-level site owners / responsible groups)."""

from __future__ import annotations

import typer

from pdfscan.service import ScannerService

owner_app = typer.Typer(help="Manage site owners (responsible org groups).", no_args_is_help=True)


def _svc(ctx: typer.Context) -> ScannerService:
    return ScannerService(ctx.obj)


@owner_app.command("add")
def owner_add(
    ctx: typer.Context,
    key: str = typer.Argument(..., help="Owner key (e.g. a content-manager security group)."),
    label: str | None = typer.Option(None, "--label", help="Human-readable label."),
    notes: str | None = typer.Option(None, "--notes"),
) -> None:
    """Add or update a site owner."""
    _svc(ctx).add_owner(key, label=label, notes=notes)
    typer.echo(f"Saved owner '{key}'")


@owner_app.command("list")
def owner_list(ctx: typer.Context) -> None:
    """List site owners with member and site counts."""
    owners = _svc(ctx).list_owners()
    if not owners:
        typer.echo("No owners. Add one with: pdfscan owner add <key>")
        return
    for o in owners:
        label = f" ({o['label']})" if o["label"] else ""
        typer.echo(f"{o['key']}{label}: {o['members']} people, {o['sites']} sites")


@owner_app.command("show")
def owner_show(ctx: typer.Context, key: str) -> None:
    """Show an owner's sites and member people."""
    detail = _svc(ctx).show_owner(key)
    if not detail:
        typer.echo(f"No such owner '{key}'.")
        raise typer.Exit(code=1)
    typer.echo(f"owner: {detail['key']}")
    if detail["label"]:
        typer.echo(f"label: {detail['label']}")
    if detail["notes"]:
        typer.echo(f"notes: {detail['notes']}")
    typer.echo(f"sites: {', '.join(detail['sites']) or '-'}")
    typer.echo("members:")
    if not detail["members"]:
        typer.echo("  (none)")
    for m in detail["members"]:
        mgr = " [manager]" if m["is_manager"] else ""
        typer.echo(f"  {m['name']} <{m['email'] or '-'}> ({m['employee_id']}){mgr}")


@owner_app.command("remove")
def owner_remove(ctx: typer.Context, key: str) -> None:
    """Remove an owner (sites referencing it are left without an owner)."""
    ok = _svc(ctx).remove_owner(key)
    typer.echo(f"Removed owner '{key}'" if ok else f"No such owner '{key}'")
