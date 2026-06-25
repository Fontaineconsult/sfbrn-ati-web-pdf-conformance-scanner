"""`pdfscan eval <dir>` - score the classifier against pre-sorted ground-truth PDFs."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from pdfscan.config import Settings
from pdfscan.service import ScannerError, ScannerService


def _settings(ctx: typer.Context) -> Settings:
    return ctx.obj


def _print_report(report: dict) -> None:
    from rich.console import Console
    from rich.table import Table

    from pdfscan.classify.evaluate import EVAL_LABELS

    console = Console()
    acc = report["accuracy"]
    console.print(
        f"[bold]Accuracy:[/] {acc:.1%}  ({report['total']} PDFs, "
        f"{len(report['mismatches'])} mismatched)"
    )

    # Confusion matrix: rows = expected, cols = predicted.
    short = {"good_to_go": "GO", "fit_for_automated_tagging": "AUTO", "needs_manual_remediation": "MANUAL"}
    matrix = Table(title="Confusion (row=expected, col=predicted)", header_style="bold")
    matrix.add_column("expected \\ pred")
    for lab in EVAL_LABELS:
        matrix.add_column(short[lab], justify="right")
    confusion = report["confusion"]
    for exp in EVAL_LABELS:
        cells = []
        for pred in EVAL_LABELS:
            n = confusion.get(exp, {}).get(pred, 0)
            cells.append(f"[green]{n}[/]" if exp == pred and n else str(n))
        matrix.add_row(short[exp], *cells)
    console.print(matrix)

    # Per-class precision/recall.
    pc = Table(title="Per-class", header_style="bold")
    pc.add_column("class")
    pc.add_column("precision", justify="right")
    pc.add_column("recall", justify="right")
    pc.add_column("support", justify="right")
    for lab in EVAL_LABELS:
        m = report["per_class"].get(lab, {})
        pc.add_row(
            short[lab],
            f"{m.get('precision', 0.0):.0%}",
            f"{m.get('recall', 0.0):.0%}",
            str(int(m.get("support", 0))),
        )
    console.print(pc)

    # Mismatches with the signals + reason behind each miss (the tuning fuel).
    misses = report["mismatches"]
    if not misses:
        console.print("[green]No mismatches -- the profile matches your sorting.[/]")
        return
    mm = Table(title="Mismatches", header_style="bold")
    mm.add_column("PDF", overflow="fold", max_width=40)
    mm.add_column("expected")
    mm.add_column("predicted")
    mm.add_column("signals", overflow="fold", max_width=44)
    mm.add_column("reason", overflow="fold", max_width=40)
    for it in misses:
        sig = it.get("signals", {})
        sig_str = ", ".join(f"{k}={v}" for k, v in sig.items() if v not in (None, [], False))
        mm.add_row(
            Path(it["path"]).name,
            f"[cyan]{short.get(it['expected'], it['expected'])}[/]",
            f"[red]{short.get(it['predicted'], it['predicted'])}[/]",
            sig_str or "[dim]-[/]",
            it.get("reason", ""),
        )
    console.print(mm)


def evaluate(
    ctx: typer.Context,
    path: Path = typer.Argument(..., help="Directory of category subfolders of labelled PDFs."),
    profile: Path | None = typer.Option(
        None, "--profile", help="Candidate classification.yaml to score (default: configured)."
    ),
    json_out: Path | None = typer.Option(
        None, "--json", help="Write the full report (incl. mismatches) to this JSON file."
    ),
) -> None:
    """Classify pre-sorted PDFs and report accuracy / confusion / mismatches.

    Layout: ``<path>/good_to_go/*.pdf``, ``<path>/fit_for_automated_tagging/*.pdf``
    (aliases auto/fit), ``<path>/needs_manual_remediation/*.pdf`` (alias manual).
    The JSON report's mismatch list is the feedback artifact for tuning
    ``config/classification.yaml``.
    """
    settings = _settings(ctx)
    svc = ScannerService(settings)
    try:
        report = svc.evaluate(path, profile_path=str(profile) if profile else None)
    except ScannerError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc

    _print_report(report)
    if json_out:
        json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        typer.echo(f"Wrote report to {json_out}")
