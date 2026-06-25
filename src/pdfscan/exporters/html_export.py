"""Self-contained HTML accessibility report, grouped + colour-coded by status.

Renders the same joined rows the other exporters consume (so it carries the
read-time ``classification`` / ``classification_reason`` and owner/responsible
info) into a single standalone ``.html`` file -- no external CSS/JS, safe to
email or open offline. PDFs are grouped into colour-demarcated sections by
remediation status (needs-manual / auto-taggable / good-to-go / pending), with
summary tiles up top. Styling takes cues from the original tool's report
(brand header bar, banded tables) but adds explicit per-status colour coding.
"""

from __future__ import annotations

import html
import os
from datetime import datetime
from pathlib import Path

# (classification value, heading, css-key, one-line blurb)
_STATUS_META = [
    (
        "needs_manual_remediation",
        "Needs manual remediation",
        "manual",
        "A human must remediate these (scanned/image-only, forms, complex tables/graphics, or many violations).",
    ),
    (
        "fit_for_automated_tagging",
        "Fit for automated tagging",
        "auto",
        "An auto-tagger (Adobe Autotag / PDFix) can likely fix these with light review.",
    ),
    (
        "good_to_go",
        "Good to go",
        "go",
        "Tagged with no counted violations -- no action needed.",
    ),
    (
        "pending",
        "Pending verification",
        "pending",
        "Discovered but not yet verified with veraPDF.",
    ),
]

_CSS = """
:root{
  --ink:#333; --muted:#6b7280; --line:#dddddd;
  --head:#003262; --accent:#c4820e;
  --go:#2e7d32; --auto:#b26a00; --manual:#c62828; --pending:#6b7280;
  --go-bg:#f2f8f3; --auto-bg:#fbf6ea; --manual-bg:#fdf2f1; --pending-bg:#f5f6f7;
}
*{box-sizing:border-box}
body{font-family:Arial,Helvetica,sans-serif;line-height:1.55;color:var(--ink);
  background:#fff;margin:0}
.wrap{max-width:980px;margin:0 auto;padding:28px 24px}
h1{color:var(--head);font-size:22px;margin:0;border-bottom:3px solid var(--accent);
  padding-bottom:10px}
.meta{color:var(--muted);font-size:13px;margin:10px 0 0}
.meta b{color:var(--ink)}
.tiles{display:flex;gap:10px;flex-wrap:wrap;margin:22px 0}
.tile{flex:1 1 130px;border:1px solid var(--line);border-radius:6px;padding:12px 14px}
.tile .n{font-size:22px;font-weight:700;line-height:1}
.tile .l{font-size:12px;color:var(--muted);margin-top:5px}
.tile.go .n{color:var(--go)} .tile.auto .n{color:var(--auto)} .tile.manual .n{color:var(--manual)}
section.status{margin:24px 0}
.status-head{display:flex;align-items:baseline;gap:10px;padding:8px 12px;
  border-left:4px solid var(--line);background:#fafafa}
.status-head h2{margin:0;font-size:15px;font-weight:700}
.status-head .count{color:var(--muted);font-weight:400}
.status-head .blurb{font-size:12px;color:var(--muted);margin-left:auto;font-weight:400}
.status.go .status-head{border-left-color:var(--go);background:var(--go-bg)}
.status.auto .status-head{border-left-color:var(--auto);background:var(--auto-bg)}
.status.manual .status-head{border-left-color:var(--manual);background:var(--manual-bg)}
.status.pending .status-head{border-left-color:var(--pending);background:var(--pending-bg)}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px}
th,td{padding:8px 10px;border:1px solid var(--line);text-align:left;vertical-align:top}
th{background:var(--head);color:#fff;font-weight:600}
tr:nth-child(even) td{background:#f7f8fa}
.url{word-break:break-all}
.url a{color:var(--head);text-decoration:none}
.url a:hover{text-decoration:underline}
.reason{color:var(--muted);font-size:12px;margin-top:3px}
.num{text-align:right}
.num.bad{color:var(--manual);font-weight:700}
.yn-y{color:var(--go)} .yn-n{color:var(--manual)}
.flag{font-size:12px;white-space:nowrap}
.flag.img{color:var(--manual)} .flag.form{color:var(--auto)} .flag.cg{color:#6a4fb3}
.src{color:var(--muted);font-size:12px}
.dim{color:#aab0b6}
footer{margin-top:26px;padding-top:14px;border-top:1px solid var(--line);
  color:var(--muted);font-size:12px}
@media print{.status-head .blurb{display:none}}
"""


def _esc(value: object) -> str:
    return html.escape("" if value is None else str(value))


def _deschemed(url: str) -> str:
    for prefix in ("https://", "http://"):
        if url.startswith(prefix):
            return url[len(prefix) :]
    return url


def _yn(value: object, *, good_is_true: bool = True) -> str:
    truthy = bool(value)
    good = truthy if good_is_true else not truthy
    cls = "yn-y" if good else "yn-n"
    return f'<span class="{cls}">{"Y" if truthy else "N"}</span>'


def _is_verified(row: dict) -> bool:
    return row.get("violations") is not None


def _source_note(row: dict) -> str:
    tokens: list[str] = []
    if row.get("offsite"):
        via = row.get("via_resolver")
        tokens.append(f"offsite{':' + _esc(via) if via else ''}")
    if row.get("pdf_404"):
        tokens.append("404")
    if row.get("archived"):
        tokens.append("archived")
    return f' <span class="src">{" &middot; ".join(tokens)}</span>' if tokens else ""


def _row_html(row: dict, idx: int) -> str:
    url = row.get("pdf_url", "")
    disp = _deschemed(url)
    reason = row.get("classification_reason")
    reason_html = f'<div class="reason">{_esc(reason)}</div>' if reason else ""
    if not _is_verified(row):
        # Pending: only the crawl-side facts are known.
        return (
            f"<tr><td class='num dim'>{idx}</td>"
            f"<td class='url'><a href='{_esc(url)}' title='{_esc(url)}'>{_esc(disp)}</a>"
            f"{_source_note(row)}</td>"
            f"<td colspan='9' class='dim'>not yet verified</td></tr>"
        )

    viol = row.get("violations") or 0
    viol_cls = "num bad" if viol else "num"
    flags: list[str] = []
    if row.get("image_only"):
        flags.append('<span class="flag img">image-only</span>')
    if row.get("has_form"):
        flags.append('<span class="flag form">form</span>')
    if row.get("complex_graphic"):
        flags.append('<span class="flag cg">complex graphic</span>')
    flags_html = ", ".join(flags) or '<span class="dim">-</span>'
    pages = row.get("page_count")
    return (
        f"<tr><td class='num dim'>{idx}</td>"
        f"<td class='url'><a href='{_esc(url)}' title='{_esc(url)}'>{_esc(disp)}</a>"
        f"{_source_note(row)}{reason_html}</td>"
        f"<td>{flags_html}</td>"
        f"<td>{_yn(row.get('tagged'))}</td>"
        f"<td class='{viol_cls}'>{viol}</td>"
        f"<td class='num'>{_esc(row.get('failed_checks') or 0)}</td>"
        f"<td class='num'>{_esc(pages) if pages is not None else '-'}</td>"
        f"<td>{_yn(row.get('title_set'))}</td>"
        f"<td>{_yn(row.get('language_set'))}</td>"
        f"<td>{_esc(row.get('text_type') or '-')}</td></tr>"
    )


def _section_html(meta: tuple[str, str, str, str], rows: list[dict]) -> str:
    _value, heading, css, blurb = meta
    if not rows:
        return ""
    ordered = sorted(rows, key=lambda r: (-(r.get("violations") or 0), r.get("pdf_url", "")))
    body = "".join(_row_html(r, i) for i, r in enumerate(ordered, 1))
    head = (
        '<thead><tr><th class="num">#</th><th>PDF</th><th>Flags</th><th>Tag</th>'
        "<th>Viol</th><th>Failed</th><th>Pages</th><th>Title</th><th>Lang</th>"
        "<th>Text</th></tr></thead>"
    )
    return (
        f'<section class="status {css}">'
        f'<div class="status-head"><h2>{_esc(heading)}</h2>'
        f'<span class="count">{len(rows)}</span>'
        f'<span class="blurb">{_esc(blurb)}</span></div>'
        f"<table>{head}<tbody>{body}</tbody></table></section>"
    )


def _tiles_html(rows: list[dict], by_status: dict[str, list[dict]]) -> str:
    verified = sum(1 for r in rows if _is_verified(r))
    tiles = [
        ("", "Discovered", len(rows)),
        ("", "Verified", verified),
        ("go", "Good to go", len(by_status["good_to_go"])),
        ("auto", "Auto-taggable", len(by_status["fit_for_automated_tagging"])),
        ("manual", "Needs manual", len(by_status["needs_manual_remediation"])),
    ]
    return '<section class="tiles">' + "".join(
        f'<div class="tile {cls}"><div class="n">{n}</div><div class="l">{_esc(label)}</div></div>'
        for cls, label, n in tiles
    ) + "</section>"


def _header_html(rows: list[dict]) -> str:
    sites = sorted({r.get("site") for r in rows if r.get("site")})
    site_label = sites[0] if len(sites) == 1 else f"{len(sites)} sites"
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    owner = rows[0].get("owner") if rows else None
    responsible = rows[0].get("responsible") if rows else None
    meta = [f"Site <b>{_esc(site_label)}</b>", f"{len(rows)} PDFs", f"generated {generated}"]
    if owner:
        meta.append(f"owner <b>{_esc(owner)}</b>")
    if responsible:
        meta.append(f"responsible: {_esc(responsible)}")
    return (
        "<h1>PDF Accessibility Report</h1>"
        f'<div class="meta">{" &middot; ".join(meta)}</div>'
    )


def render_html(rows: list[dict]) -> str:
    """Render the joined rows into a complete standalone HTML document."""
    by_status: dict[str, list[dict]] = {value: [] for value, *_ in _STATUS_META}
    for row in rows:
        status = (row.get("classification") if _is_verified(row) else "pending") or "pending"
        by_status.setdefault(status, []).append(row)

    sections = "".join(_section_html(meta, by_status.get(meta[0], [])) for meta in _STATUS_META)
    site_title = ""
    sites = sorted({r.get("site") for r in rows if r.get("site")})
    if len(sites) == 1:
        site_title = f" — {_esc(sites[0])}"
    return (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>PDF Accessibility Report{site_title}</title>"
        f"<style>{_CSS}</style></head><body><div class='wrap'>"
        f"{_header_html(rows)}"
        f"{_tiles_html(rows, by_status)}"
        f"{sections}"
        "<footer>Generated by pdfscan. Status is a read-time heuristic "
        "(good_to_go / fit_for_automated_tagging / needs_manual_remediation) and is "
        "tunable via config/classification.yaml.</footer>"
        "</div></body></html>"
    )


def export_html(rows: list[dict], out_path: str | os.PathLike) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(rows), encoding="utf-8")
    return out
