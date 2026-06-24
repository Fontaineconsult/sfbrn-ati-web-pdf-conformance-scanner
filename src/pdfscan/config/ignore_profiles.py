"""veraPDF rule handling: acrobat-safe ignores + immediate-failure flags."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class IgnoreProfiles:
    # clause -> set of testNumbers to ignore (not counted as violations)
    ignore: dict[str, set[str]]
    # clause -> {testNumber -> flag name ("tagged" | "image_only")}
    immediate_failures: dict[str, dict[str, str]]

    def is_ignored(self, clause: str | int, test_number: str | int) -> bool:
        return str(test_number) in self.ignore.get(str(clause), set())

    def flag_for(self, clause: str | int, test_number: str | int) -> str | None:
        return self.immediate_failures.get(str(clause), {}).get(str(test_number))


def load_ignore_profiles(path: str | os.PathLike) -> IgnoreProfiles:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    ignore = {
        str(clause): {str(t) for t in tests}
        for clause, tests in (data.get("ignore") or {}).items()
    }
    immediate = {
        str(clause): {str(t): str(flag) for t, flag in mapping.items()}
        for clause, mapping in (data.get("immediate_failures") or {}).items()
    }
    return IgnoreProfiles(ignore=ignore, immediate_failures=immediate)
