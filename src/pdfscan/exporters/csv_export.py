from __future__ import annotations

import csv
import os
from pathlib import Path

from pdfscan.exporters.base import COLUMNS


def export_csv(rows: list[dict], out_path: str | os.PathLike) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return out
