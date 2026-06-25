"""`pdfscan people import ...` — bulk-load owners/people/assignments from CSV."""

from __future__ import annotations

from pathlib import Path

import typer

from pdfscan.service import ScannerService

people_app = typer.Typer(help="Bulk-import owners and responsible people.", no_args_is_help=True)


@people_app.command("import")
def people_import(
    ctx: typer.Context,
    sites: Path | None = typer.Option(None, "--sites", help="sites.csv (Domain, Security_Group)."),
    employees: Path | None = typer.Option(
        None, "--employees", help="employees.csv (Full Name, Employee ID, Email)."
    ),
    managers: Path | None = typer.Option(
        None, "--managers", help="managers.csv (one Employee ID per line)."
    ),
    assignments: Path | None = typer.Option(
        None, "--assignments", help="site_assignments.csv (Security_Group, Name, ID, Email)."
    ),
) -> None:
    """Import any combination of the CSV roster files (each optional)."""
    if not any([sites, employees, managers, assignments]):
        typer.echo("Provide at least one of --sites / --employees / --managers / --assignments.")
        raise typer.Exit(code=1)
    rep = ScannerService(ctx.obj).import_people(
        sites=sites, employees=employees, managers=managers, assignments=assignments
    )
    typer.echo(
        f"owners +{rep['owners_created']}, people +{rep['people_created']}, "
        f"managers {rep['managers_marked']}, memberships +{rep['memberships_added']}, "
        f"sites linked {rep['sites_linked']}"
    )
    if rep["sites_unmatched"]:
        n = len(rep["sites_unmatched"])
        typer.echo(f"  unmatched domains ({n}): {', '.join(rep['sites_unmatched'][:10])}")
    if rep["ambiguous"]:
        n = len(rep["ambiguous"])
        typer.echo(f"  ambiguous domains ({n}): {', '.join(rep['ambiguous'][:10])}")
    for w in rep["warnings"][:10]:
        typer.echo(f"  warning: {w}")
