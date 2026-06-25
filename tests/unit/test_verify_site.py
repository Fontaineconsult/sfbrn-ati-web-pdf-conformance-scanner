"""Orchestration test for the batched verify_site pipeline.

Download and veraPDF are stubbed so the test exercises the pipeline's logic
(URL dedup, content-hash dedup/reuse, batching, failure isolation, counts,
persistence) against a real temp DB -- no network or JVM required.
"""

from __future__ import annotations

import copy
from pathlib import Path

from pdfscan.config import IgnoreProfiles
from pdfscan.config.settings import DEFAULTS, Settings
from pdfscan.db.repositories import (
    FailureRepository,
    PdfRepository,
    ReportRepository,
    SiteRepository,
)
from pdfscan.models import DiscoveredPdf, Site, SiteConfig
from pdfscan.pdf import verify as verify_mod
from pdfscan.pdf.verify import verify_site

PARENT = "https://x/page"
CONTENT = {
    "https://x/good1.pdf": b"%PDF-1.7 AAAA",   # same bytes as good2 -> one report
    "https://x/good2.pdf": b"%PDF-1.7 AAAA",
    "https://x/good3.pdf": b"%PDF-1.7 BBBB",   # distinct content
    "https://x/page.pdf": b"<html>not a pdf</html>",  # fails the magic-byte gate
}
BOOM = "https://x/boom.pdf"  # download raises


def _fake_download(url, dest, *, timeout=30, max_bytes=None, ssl_insecure_retry=True):
    if url == BOOM:
        raise RuntimeError("connection refused")
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    Path(dest).write_bytes(CONTENT[url])


def _fake_batch(paths, cmd, flavour="ua1", timeout=1800):
    # One failing rule per file: 7.1/11 -> the ignore profile flags it "tagged".
    rule = {"clause": "7.1", "testNumber": "11", "failedChecks": 1}
    return {
        Path(p).name: {
            "itemDetails": {"name": str(p)},
            "validationResult": {"details": {"ruleSummaries": [rule]}},
        }
        for p in paths
    }


def _settings(tmp_path) -> Settings:
    return Settings(raw=copy.deepcopy(DEFAULTS), base_dir=tmp_path)


def test_verify_site_dedup_reuse_failures_and_counts(conn, tmp_path, monkeypatch):
    monkeypatch.setattr(verify_mod, "download_to_file", _fake_download)
    monkeypatch.setattr(verify_mod, "run_verapdf_batch", _fake_batch)

    sid = SiteRepository(conn).add(
        Site(id=None, name="t", config=SiteConfig(seeds=["https://x"]))
    )
    pdfs = PdfRepository(conn)
    urls = list(CONTENT) + [BOOM]
    for u in urls:
        pdfs.upsert(DiscoveredPdf(u, PARENT, sid))

    ignore = IgnoreProfiles(ignore={}, immediate_failures={"7.1": {"11": "tagged"}})
    rows = pdfs.list_unverified(sid)
    counts = verify_site(
        conn, rows, _settings(tmp_path), "verapdf-cmd", ignore,
        site_name="t", storage_template=DEFAULTS["storage"]["template"], workers=3, batch_size=50,
    )

    # good1+good3 are distinct new hashes (verified); good2 reuses good1's report;
    # page.pdf (not a PDF) and boom (download error) fail.
    assert counts == {"verified": 2, "reused": 1, "failed": 2}

    reports = ReportRepository(conn)
    by_url = {p.pdf_url: p for p in pdfs.list_by_site(sid)}
    h1, h2, h3 = (by_url[f"https://x/good{i}.pdf"].file_hash for i in (1, 2, 3))
    assert h1 is not None and h1 == h2 and h3 is not None and h3 != h1  # content dedup

    rep = reports.get_by_hash(h1)
    assert rep.violations == 1 and rep.tagged is False  # 7.1/11 flagged "tagged"
    assert [r.clause for r in reports.list_rules(h1)] == ["7.1"]

    # failed rows stay unverified (resumable); failures recorded.
    assert by_url["https://x/page.pdf"].file_hash is None
    assert by_url[BOOM].file_hash is None
    assert FailureRepository(conn).count_by_site(sid) >= 2

    # content-addressed remediation copies exist, one per unique hash.
    saved = list((tmp_path / "remediation" / "t").glob("*.pdf"))
    assert len(saved) == 2
