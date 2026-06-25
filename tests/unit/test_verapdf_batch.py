from __future__ import annotations

import json
import types

import pytest

from pdfscan.pdf import verapdf
from pdfscan.pdf.verapdf import rules_from_job, run_verapdf_batch


def _job(name: str, rules: list[dict]) -> dict:
    return {
        "itemDetails": {"name": name},
        "validationResult": {"details": {"ruleSummaries": rules}},
    }


def _proc(stdout: str):
    return types.SimpleNamespace(stdout=stdout, stderr="", returncode=0)


def test_run_verapdf_batch_maps_jobs_by_basename(monkeypatch):
    report = {
        "report": {
            "jobs": [
                _job("/abs/tmp/verify_1_0.pdf", [{"clause": "7.1", "testNumber": "11", "failedChecks": 1}]),
                _job("verify_1_1.pdf", [{"clause": "7.2", "testNumber": "999", "failedChecks": 4}]),
            ]
        }
    }
    monkeypatch.setattr(verapdf.subprocess, "run", lambda *a, **k: _proc(json.dumps(report)))

    out = run_verapdf_batch(["/x/verify_1_0.pdf", "/x/verify_1_1.pdf"], "verapdf")
    assert set(out) == {"verify_1_0.pdf", "verify_1_1.pdf"}

    rules = rules_from_job(out["verify_1_0.pdf"])
    assert (rules[0].clause, rules[0].test_number, rules[0].failed_checks) == ("7.1", "11", 1)


def test_run_verapdf_batch_empty_paths_short_circuits():
    assert run_verapdf_batch([], "verapdf") == {}


def test_run_verapdf_batch_invalid_json_raises(monkeypatch):
    monkeypatch.setattr(verapdf.subprocess, "run", lambda *a, **k: _proc("<<not json>>"))
    with pytest.raises(RuntimeError):
        run_verapdf_batch(["/x/a.pdf"], "verapdf")


# --- real veraPDF (skipped when the binary/Java is unavailable, e.g. in CI) ----
def _verapdf_cmd_or_skip() -> str:
    from pdfscan.config import load_settings
    from pdfscan.verapdf_dist import resolve_verapdf

    cmd = resolve_verapdf(load_settings())
    if not cmd:
        pytest.skip("veraPDF not available in this environment")
    return cmd


def test_run_verapdf_batch_real_invocation(tmp_path):
    import pikepdf

    cmd = _verapdf_cmd_or_skip()
    paths = []
    for i in range(2):
        p = tmp_path / f"doc_{i}.pdf"
        pdf = pikepdf.new()
        pdf.add_blank_page()
        pdf.save(p)
        paths.append(p)

    out = run_verapdf_batch(paths, cmd, "ua1", 300)
    # One JVM invocation validated both files; results keyed by basename.
    assert set(out) == {"doc_0.pdf", "doc_1.pdf"}
    for job in out.values():
        assert isinstance(rules_from_job(job), list)
