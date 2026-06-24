"""`pdfscan export csv|json|excel <site> --out PATH`."""

from __future__ import annotations

from pathlib import Path

import typer

from pdfscan.config import Settings
from pdfscan.exporters import collect_rows, export_csv, export_excel, export_json

export_app = typer.Typer(help="Export results (csv/json/excel).", no_args_is_help=True)

_WRITERS = {"csv": export_csv, "json": export_json, "excel": export_excel}


def _settings(ctx: typer.Context) -> Settings:
    return ctx.obj


def _export(ctx: typer.Context, fmt: str, site: str | None, out: Path, all_sites: bool) -> None:
    settings = _settings(ctx)
    if not site and not all_sites:
        typer.echo("Specify a site name or --all.")
        raise typer.Exit(code=1)
    try:
        rows = collect_rows(settings, None if all_sites else site)
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    path = _WRITERS[fmt](rows, out)
    typer.echo(f"Wrote {len(rows)} rows to {path}")


@export_app.command("csv")
def export_csv_cmd(
    ctx: typer.Context,
    site: str | None = typer.Argument(None),
    out: Path = typer.Option(..., "--out", "-o"),
    all_sites: bool = typer.Option(False, "--all"),
) -> None:
    _export(ctx, "csv", site, out, all_sites)


@export_app.command("json")
def export_json_cmd(
    ctx: typer.Context,
    site: str | None = typer.Argument(None),
    out: Path = typer.Option(..., "--out", "-o"),
    all_sites: bool = typer.Option(False, "--all"),
) -> None:
    _export(ctx, "json", site, out, all_sites)


@export_app.command("excel")
def export_excel_cmd(
    ctx: typer.Context,
    site: str | None = typer.Argument(None),
    out: Path = typer.Option(..., "--out", "-o"),
    all_sites: bool = typer.Option(False, "--all"),
) -> None:
    _export(ctx, "excel", site, out, all_sites)
