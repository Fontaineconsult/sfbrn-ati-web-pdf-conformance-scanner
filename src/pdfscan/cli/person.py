"""`pdfscan person ...` commands + `pdfscan whois <site>`."""

from __future__ import annotations

import typer

from pdfscan.service import ScannerError, ScannerService


def _svc(ctx: typer.Context) -> ScannerService:
    return ScannerService(ctx.obj)


person_app = typer.Typer(help="Manage responsible people.", no_args_is_help=True)


@person_app.command("add")
def person_add(
    ctx: typer.Context,
    employee_id: str = typer.Argument(..., help="Unique employee id."),
    full_name: str = typer.Argument(..., help="Full name."),
    email: str | None = typer.Option(None, "--email"),
    manager: bool = typer.Option(False, "--manager/--no-manager", help="Mark as a manager."),
) -> None:
    """Add or update a person."""
    _svc(ctx).add_person(employee_id, full_name, email=email, is_manager=manager)
    typer.echo(f"Saved person '{full_name}' ({employee_id})")


@person_app.command("list")
def person_list(ctx: typer.Context) -> None:
    """List people."""
    people = _svc(ctx).list_people()
    if not people:
        typer.echo("No people. Add one with: pdfscan person add <id> <name>")
        return
    for p in people:
        mgr = " [manager]" if p["is_manager"] else ""
        typer.echo(f"{p['name']} <{p['email'] or '-'}> ({p['employee_id']}){mgr}")


@person_app.command("remove")
def person_remove(ctx: typer.Context, employee_id: str) -> None:
    """Remove a person (and their owner memberships)."""
    ok = _svc(ctx).remove_person(employee_id)
    typer.echo(f"Removed person '{employee_id}'" if ok else f"No such person '{employee_id}'")


@person_app.command("assign")
def person_assign(ctx: typer.Context, employee_id: str, owner_key: str) -> None:
    """Make a person a member of an owner org."""
    try:
        added = _svc(ctx).assign_person(employee_id, owner_key)
    except ScannerError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    typer.echo(f"Assigned {employee_id} to {owner_key}" if added else "Already assigned")


@person_app.command("unassign")
def person_unassign(ctx: typer.Context, employee_id: str, owner_key: str) -> None:
    """Remove a person's membership in an owner org."""
    try:
        removed = _svc(ctx).unassign_person(employee_id, owner_key)
    except ScannerError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    typer.echo(f"Unassigned {employee_id} from {owner_key}" if removed else "Was not assigned")


def whois(ctx: typer.Context, name: str = typer.Argument(..., help="Site name.")) -> None:
    """Show who is responsible for a site (owner org + member people)."""
    try:
        info = _svc(ctx).whois(name)
    except ScannerError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    owner = info["owner"]
    if not owner:
        typer.echo(f"Site '{name}' has no owner assigned.")
        typer.echo("Assign one with: pdfscan site set-owner <name> <owner-key>")
        return
    label = f" ({info['owner_label']})" if info["owner_label"] else ""
    typer.echo(f"Site '{name}' owner: {owner}{label}")
    if not info["responsible"]:
        typer.echo("  no people assigned to this owner yet.")
        return
    typer.echo("  responsible:")
    for p in info["responsible"]:
        mgr = " [manager]" if p["is_manager"] else ""
        typer.echo(f"    {p['name']} <{p['email'] or '-'}>{mgr}")
