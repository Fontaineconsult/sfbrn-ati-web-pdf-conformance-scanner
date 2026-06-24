from __future__ import annotations

import csv
import json

from openpyxl import load_workbook

from pdfscan.exporters import COLUMNS, export_csv, export_excel, export_json


def _sample():
    row = dict.fromkeys(COLUMNS, None)
    row.update({"site": "hr", "pdf_url": "https://x/a.pdf", "violations": 3,
                "tagged": 1, "page_count": 5, "offsite": 0})
    return [row]


def test_csv_roundtrip(tmp_path):
    p = export_csv(_sample(), tmp_path / "o.csv")
    with open(p, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert list(rows[0].keys()) == COLUMNS
    assert rows[0]["site"] == "hr"
    assert rows[0]["violations"] == "3"


def test_json_roundtrip(tmp_path):
    p = export_json(_sample(), tmp_path / "o.json")
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data[0]["pdf_url"].endswith("a.pdf")
    assert data[0]["page_count"] == 5


def test_excel_headers_and_rows(tmp_path):
    p = export_excel(_sample(), tmp_path / "o.xlsx")
    ws = load_workbook(p).active
    assert [c.value for c in ws[1]] == COLUMNS
    assert ws.max_row == 2
