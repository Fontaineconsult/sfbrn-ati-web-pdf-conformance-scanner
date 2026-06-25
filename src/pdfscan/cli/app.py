"""pdfscan command-line interface (Typer).

Sub-apps (site/crawl/verify/run/export/status/archive/db/setup) are registered
here as their modules come online. Each ultimately delegates to
``pdfscan.service.facade.ScannerService`` so the CLI, MCP server, and Skill
share one implementation.
"""

from __future__ import annotations

from pathlib import Path

import typer

from pdfscan import __version__
from pdfscan.cli.archive import archive_app
from pdfscan.cli.crawl import crawl
from pdfscan.cli.db import db_app
from pdfscan.cli.evaluate import evaluate
from pdfscan.cli.export import export_app
from pdfscan.cli.owner import owner_app
from pdfscan.cli.people import people_app
from pdfscan.cli.person import person_app, whois
from pdfscan.cli.run import run
from pdfscan.cli.setup import doctor, setup_verapdf
from pdfscan.cli.site import site_app
from pdfscan.cli.status import check_404, rules, status
from pdfscan.cli.verify import verify
from pdfscan.config import load_settings

app = typer.Typer(
    name="pdfscan",
    help="Crawl websites for PDFs and verify accessibility with veraPDF.",
    no_args_is_help=True,
    add_completion=False,
)

app.add_typer(db_app, name="db")
app.add_typer(site_app, name="site")
app.add_typer(owner_app, name="owner")
app.add_typer(person_app, name="person")
app.add_typer(people_app, name="people")
app.add_typer(export_app, name="export")
app.add_typer(archive_app, name="archive")
app.command("crawl")(crawl)
app.command("verify")(verify)
app.command("run")(run)
app.command("status")(status)
app.command("rules")(rules)
app.command("eval")(evaluate)
app.command("whois")(whois)
app.command("check-404")(check_404)
app.command("setup-verapdf")(setup_verapdf)
app.command("doctor")(doctor)


@app.callback()
def main(
    ctx: typer.Context,
    config: Path | None = typer.Option(
        None, "--config", help="Path to settings.yaml (default: ./config/settings.yaml)."
    ),
    db: Path | None = typer.Option(None, "--db", help="Override the SQLite database path."),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Verbose logging."),
) -> None:
    """Load layered settings and stash them on the context for sub-commands."""
    overrides: dict = {}
    if db is not None:
        overrides["database"] = {"path": str(db)}
    if verbose:
        overrides["logging"] = {"level": "DEBUG"}
    ctx.obj = load_settings(config_path=config, overrides=overrides)


@app.command()
def version() -> None:
    """Print the pdfscan version."""
    typer.echo(f"pdfscan {__version__}")


if __name__ == "__main__":
    app()
