"""`pdfscan status <site>` summary/table and `pdfscan check-404 <site>`."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from urllib.parse import urlsplit

import typer

from pdfscan.classify import Label, classify_rows
from pdfscan.config import Settings
from pdfscan.db import session
from pdfscan.db.repositories import (
    FailureRepository,
    PdfRepository,
    ReportRepository,
    SiteOwnerRepository,
    SiteRepository,
)


def _settings(ctx: typer.Context) -> Settings:
    return ctx.obj


def _load_policies(settings: Settings):
    """Resolve the ignore + classification policies (both tolerate a missing file)."""
    from pdfscan.config import load_classification_profile, load_ignore_profiles

    ignore = load_ignore_profiles(
        settings.resolve_path(
            settings.get("verapdf.ignore_profiles") or "config/ignore_profiles.yaml"
        )
    )
    profile = load_classification_profile(
        settings.resolve_path(
            settings.get("classification.profile") or "config/classification.yaml"
        )
    )
    return ignore, profile


# -- pure helpers (filtering/sorting over export_rows() dicts) -----------------
def _is_verified(r: dict) -> bool:
    """A PDF is 'verified' once a veraPDF report exists for its hash."""
    return r["violations"] is not None


def _has_issue(r: dict) -> bool:
    """Verified row with an accessibility problem worth remediating."""
    if not _is_verified(r):
        return False
    return (r["violations"] or 0) > 0 or not r["tagged"] or bool(r["image_only"])


class StatusFilter(StrEnum):
    all = "all"
    verified = "verified"
    pending = "pending"
    issues = "issues"
    offsite = "offsite"
    archived = "archived"
    broken = "broken"  # pdf or parent 404
    good_to_go = "good_to_go"  # remediation triage class
    auto = "auto"  # fit_for_automated_tagging
    manual = "manual"  # needs_manual_remediation


class StatusSort(StrEnum):
    url = "url"
    violations = "violations"


_FILTERS: dict[StatusFilter, Callable[[dict], bool]] = {
    StatusFilter.all: lambda r: True,
    StatusFilter.verified: _is_verified,
    StatusFilter.pending: lambda r: not _is_verified(r),
    StatusFilter.issues: _has_issue,
    StatusFilter.offsite: lambda r: bool(r["offsite"]),
    StatusFilter.archived: lambda r: bool(r["archived"]),
    StatusFilter.broken: lambda r: bool(r["pdf_404"] or r["parent_404"]),
    # Remediation-class filters read the _class attached by classify (see status()).
    StatusFilter.good_to_go: lambda r: r.get("_class") == Label.good_to_go,
    StatusFilter.auto: lambda r: r.get("_class") == Label.fit_for_automated_tagging,
    StatusFilter.manual: lambda r: r.get("_class") == Label.needs_manual_remediation,
}


def _apply_filter(rows: list[dict], key: StatusFilter) -> list[dict]:
    return [r for r in rows if _FILTERS[key](r)]


def _sort_rows(rows: list[dict], key: StatusSort) -> list[dict]:
    if key is StatusSort.violations:
        # Most violations first; unverified (None) sink to the bottom.
        return sorted(
            rows,
            key=lambda r: (r["violations"] is None, -(r["violations"] or 0), r["pdf_url"]),
        )
    return sorted(rows, key=lambda r: r["pdf_url"])


# -- rendering -----------------------------------------------------------------
def _deschemed(url: str) -> str:
    """Drop the scheme for a more compact display (keep host + path + query)."""
    parts = urlsplit(url)
    out = parts.netloc + parts.path
    if parts.query:
        out += "?" + parts.query
    return out or url


def _crawl_flags(r: dict) -> str:
    badges: list[str] = []
    if r["offsite"]:
        badges.append("[magenta]offsite[/]")
    if r["via_resolver"]:
        badges.append(f"[cyan]via:{r['via_resolver']}[/]")
    if r["archived"]:
        badges.append("[yellow]archived[/]")
    if r["pdf_404"]:
        badges.append("[red]404[/]")
    if r["parent_404"]:
        badges.append("[red]p404[/]")
    if r["removed"]:
        badges.append("[dim]removed[/]")
    return " ".join(badges) if badges else "[dim]-[/]"


def _yn(value: object, *, good_is_true: bool = True) -> str:
    """'Y'/'N' coloured by whether the value is the desired one."""
    truthy = bool(value)
    good = truthy if good_is_true else not truthy
    colour = "green" if good else "red"
    return f"[{colour}]{'Y' if truthy else 'N'}[/]"


def _text_type_cell(text_type: str | None, image_only: bool) -> str:
    """Render pdfminer's ``text_type`` as a *diagnostic* beside the authoritative
    veraPDF image-only verdict.

    veraPDF's clause 7.1/3 flag (``image_only``) is the source of truth for the
    image-only determination; ``text_type`` is a content heuristic kept for
    insight. When pdfminer says ``"Image Only"`` but veraPDF did not flag it, the
    value is marked with ``?`` (dim) so it does not read as a competing verdict.
    """
    if not text_type:
        return "[dim]-[/]"
    if text_type == "Image Only" and not image_only:
        return "[dim]Image Only?[/]"
    return text_type


def _class_cell(label: object) -> str:
    """Compact, coloured remediation-class badge for the table's ``Class`` column."""
    s = str(label) if label is not None else ""
    if s == Label.good_to_go:
        return "[green]GO[/]"
    if s == Label.fit_for_automated_tagging:
        return "[cyan]AUTO[/]"
    if s == Label.needs_manual_remediation:
        return "[red]MANUAL[/]"
    return "[dim]-[/]"  # pending / not classified


def _verify_cells(r: dict) -> list[str]:
    """Verify-side columns: tag, img-only, violations, failed, text, pages, title, lang, form."""
    if not _is_verified(r):
        dim = "[dim]-[/]"
        return [dim] * 9
    viol = r["violations"] or 0
    viol_cell = f"[red]{viol}[/]" if viol else "[green]0[/]"
    image_only = bool(r["image_only"])
    img = "[red]IMG[/]" if image_only else "[dim].[/]"
    return [
        _yn(r["tagged"], good_is_true=True),
        img,
        viol_cell,
        str(r["failed_checks"] or 0),
        _text_type_cell(r["text_type"], image_only),
        (str(r["page_count"]) if r["page_count"] is not None else "[dim]-[/]"),
        _yn(r["title_set"], good_is_true=True),
        _yn(r["language_set"], good_is_true=True),
        "form" if r["has_form"] else "[dim].[/]",
    ]


def _render_table(
    rows: list[dict], name: str, *, filter_: StatusFilter, sort: StatusSort, limit: int
) -> None:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    selected = _sort_rows(_apply_filter(rows, filter_), sort)
    shown = selected if limit <= 0 else selected[:limit]

    title = f"PDFs for '{name}'  (filter={filter_.value}, {len(selected)} match"
    if len(shown) < len(selected):
        title += f", showing {len(shown)}"
    title += ")"

    table = Table(title=title, header_style="bold", expand=False)
    table.add_column("#", justify="right", style="dim")
    table.add_column("PDF", overflow="ellipsis", no_wrap=True, max_width=58)
    table.add_column("Crawl")
    table.add_column("Verify")
    table.add_column("Class", justify="center")
    table.add_column("Tag", justify="center")
    table.add_column("Img", justify="center")
    table.add_column("Viol", justify="right")
    table.add_column("Chk", justify="right")
    table.add_column("Text")
    table.add_column("Pg", justify="right")
    table.add_column("Ttl", justify="center")
    table.add_column("Lng", justify="center")
    table.add_column("Frm", justify="center")

    for i, r in enumerate(shown, 1):
        verify = "[green]verified[/]" if _is_verified(r) else "[dim]pending[/]"
        table.add_row(
            str(i),
            _deschemed(r["pdf_url"]),
            _crawl_flags(r),
            verify,
            _class_cell(r.get("_class")),
            *_verify_cells(r),
        )

    if not shown:
        console.print(f"No PDFs match filter '{filter_.value}' for site '{name}'.")
        return

    console.print(table)
    console.print(
        "[dim]Legend: Crawl badges = offsite/via:<resolver>/archived/404/p404. "
        "Class = remediation triage ([green]GO[/]=good to go / [cyan]AUTO[/]=fit for "
        "automated tagging / [red]MANUAL[/]=needs manual). "
        "Tag/Ttl/Lng = tagged/title/language present (Y=good). "
        "Img = image-only per veraPDF (authoritative). "
        "Text = pdfminer content type (diagnostic; '?' = disagrees with Img). "
        "Viol = veraPDF violations, Chk = failed checks.[/]"
    )


def _print_summary(
    name: str,
    rows: list[dict],
    n_fail: int,
    owner: str | None = None,
    responsible: list[dict] | None = None,
) -> None:
    total = len(rows)
    verified = [r for r in rows if _is_verified(r)]
    untagged = sum(1 for r in verified if not r["tagged"])
    image_only = sum(1 for r in verified if r["image_only"])
    with_viol = sum(1 for r in verified if (r["violations"] or 0) > 0)
    clean = sum(1 for r in verified if (r["violations"] or 0) == 0 and r["tagged"])

    typer.echo(f"Site '{name}':")
    typer.echo(f"  PDFs discovered : {total}")
    typer.echo(f"  offsite         : {sum(1 for r in rows if r['offsite'])}")
    typer.echo(f"  via resolver    : {sum(1 for r in rows if r['via_resolver'])}")
    typer.echo(f"  archived        : {sum(1 for r in rows if r['archived'])}")
    typer.echo(f"  verified        : {len(verified)}")
    typer.echo(f"    untagged      : {untagged}")
    typer.echo(f"    image-only    : {image_only}")
    typer.echo(f"    with violations: {with_viol}")
    typer.echo(f"    likely passing: {clean}")
    go = sum(1 for r in rows if r.get("_class") == Label.good_to_go)
    auto = sum(1 for r in rows if r.get("_class") == Label.fit_for_automated_tagging)
    manual = sum(1 for r in rows if r.get("_class") == Label.needs_manual_remediation)
    typer.echo("  remediation triage:")
    typer.echo(f"    good to go    : {go}")
    typer.echo(f"    auto-taggable : {auto}")
    typer.echo(f"    needs manual  : {manual}")
    typer.echo(f"  owner           : {owner or '-'}")
    if responsible:
        names = ", ".join(f"{p['name']}{'*' if p['is_manager'] else ''}" for p in responsible)
        typer.echo(f"  responsible     : {names}")
    typer.echo(f"  failures        : {n_fail}")


def status(
    ctx: typer.Context,
    name: str,
    table: bool = typer.Option(
        False, "--table", "-t", help="Render a per-PDF table instead of the summary."
    ),
    filter_: StatusFilter = typer.Option(
        StatusFilter.all, "--filter", "-f", help="Table only: which rows to include."
    ),
    sort: StatusSort = typer.Option(
        StatusSort.url, "--sort", help="Table only: row ordering."
    ),
    limit: int = typer.Option(
        50, "--limit", "-n", help="Table only: max rows (0 = all)."
    ),
) -> None:
    """Show a coverage/accessibility summary (default) or a per-PDF table (--table)."""
    settings = _settings(ctx)
    ignore, profile = _load_policies(settings)
    with session(settings.db_path) as conn:
        site = SiteRepository(conn).get_by_name(name)
        if not site:
            typer.echo(f"No such site '{name}'.")
            raise typer.Exit(code=1)
        rows = PdfRepository(conn).export_rows(site.id)
        n_fail = FailureRepository(conn).count_by_site(site.id)
        cls = classify_rows(conn, rows, ignore, profile)
        owner = SiteOwnerRepository(conn).get_by_id(site.owner_id) if site.owner_id else None
        responsible = [
            {"name": p.full_name, "is_manager": p.is_manager}
            for p in SiteRepository(conn).responsible_people(site.id)
        ]
    for r in rows:
        c = cls[r["pdf_url"]]
        r["_class"] = c.label
        r["_reason"] = c.reason

    if table:
        _render_table(rows, name, filter_=filter_, sort=sort, limit=limit)
    else:
        _print_summary(name, rows, n_fail, owner.key if owner else None, responsible)


def rules(
    ctx: typer.Context,
    name: str,
    url: str = typer.Argument(..., help="Substring of the PDF URL to inspect."),
    limit: int = typer.Option(5, "--limit", "-n", help="Max matching PDFs to show."),
) -> None:
    """Show veraPDF per-rule results for PDFs whose URL contains <url>.

    Each rule is annotated with the current ignore policy ('ignored' =
    acrobat-safe, 'counts' / a flag = counted toward violations), so editing
    ignore_profiles.yaml changes this view with no re-download.
    """
    from rich.console import Console
    from rich.table import Table

    from pdfscan.config import load_ignore_profiles

    settings = _settings(ctx)
    console = Console()
    with session(settings.db_path) as conn:
        site = SiteRepository(conn).get_by_name(name)
        if not site:
            typer.echo(f"No such site '{name}'.")
            raise typer.Exit(code=1)
        pdfs = PdfRepository(conn)
        reports = ReportRepository(conn)
        matches = [p for p in pdfs.list_by_site(site.id) if url.lower() in p.pdf_url.lower()]
        detail = [(p, reports.list_rules(p.file_hash) if p.file_hash else []) for p in matches[:limit]]

    if not matches:
        typer.echo(f"No PDFs matching '{url}' for site '{name}'.")
        return

    ignore_path = settings.resolve_path(
        settings.get("verapdf.ignore_profiles") or "config/ignore_profiles.yaml"
    )
    ignore = load_ignore_profiles(ignore_path)

    for pdf, rule_rows in detail:
        console.print(f"[bold]{_deschemed(pdf.pdf_url)}[/]")
        if not pdf.file_hash:
            console.print("  [dim]not verified yet[/]\n")
            continue
        if not rule_rows:
            console.print("  [green]no failing rules recorded[/]\n")
            continue

        table = Table(show_header=True, header_style="bold")
        table.add_column("Clause")
        table.add_column("Test", justify="right")
        table.add_column("Failed", justify="right")
        table.add_column("Policy")
        table.add_column("Description", overflow="fold", max_width=70)

        counted = 0
        for r in rule_rows:
            if ignore.is_ignored(r.clause, r.test_number):
                policy, style = "[dim]ignored[/]", "dim"
            else:
                counted += 1
                flag = ignore.flag_for(r.clause, r.test_number)
                policy = f"[red]{flag}[/]" if flag else "[yellow]counts[/]"
                style = None
            table.add_row(
                r.clause or "-",
                r.test_number or "-",
                str(r.failed_checks),
                policy,
                r.description or "",
                style=style,
            )
        console.print(table)
        console.print(
            f"  [dim]{len(rule_rows)} rules recorded; {counted} count toward violations "
            f"({len(rule_rows) - counted} acrobat-safe / ignored)[/]\n"
        )

    if len(matches) > limit:
        console.print(
            f"[dim]... {len(matches) - limit} more match; narrow --url or raise --limit.[/]"
        )


def check_404(ctx: typer.Context, name: str) -> None:
    """Refresh 404 status for a site's PDFs and parent pages."""
    settings = _settings(ctx)
    from pdfscan.pipeline.status import refresh_404

    with session(settings.db_path) as conn:
        site = SiteRepository(conn).get_by_name(name)
        if not site:
            typer.echo(f"No such site '{name}'.")
            raise typer.Exit(code=1)
        stats = refresh_404(conn, site.id, settings)
    typer.echo(
        f"Checked {stats['checked']}: pdf_404={stats['pdf_404']} parent_404={stats['parent_404']}"
    )
