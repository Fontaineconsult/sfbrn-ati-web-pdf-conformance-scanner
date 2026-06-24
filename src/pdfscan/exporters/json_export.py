from __future__ import annotations

import json
import os
from pathlib import Path


def export_json(rows: list[dict], out_path: str | os.PathLike) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    return out
