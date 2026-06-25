from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from typing import Literal

Scope = Literal["host", "subdomain", "domain", "path"]


@dataclass
class SiteConfig:
    """Per-site crawl configuration (serialized to ``site.config_json``)."""

    seeds: list[str]
    allowed_hosts: list[str] = field(default_factory=list)  # empty -> derived from seeds
    scope: Scope = "host"
    max_depth: int = 0  # 0 == unlimited
    render_js: bool = False
    obey_robots: bool = False
    download_delay: float | None = None
    concurrency: int | None = None
    resolvers: list[str] | None = None  # None -> all globally-enabled resolvers
    include_external_pdfs: bool = False
    storage_template: str | None = None  # None -> use global storage.template
    path_prefix: str | None = None  # used when scope == "path"

    def to_json(self) -> str:
        return json.dumps(dataclasses.asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> SiteConfig:
        data = json.loads(raw) if raw else {}
        names = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})


@dataclass
class Site:
    id: int | None
    name: str
    config: SiteConfig
    enabled: bool = True
    notes: str | None = None
    created_at: str | None = None
    owner_id: int | None = None  # v4: FK to site_owner (org-level responsible group)
