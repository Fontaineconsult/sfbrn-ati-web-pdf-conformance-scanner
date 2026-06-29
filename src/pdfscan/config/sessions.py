"""Scan sessions: named, isolated output workspaces.

A *session* is a named workspace root. Selecting one relocates **every** output
-- database, exports/reports, saved PDF copies, scratch -- under that root, so
different scans (clients, audits, point-in-time snapshots) never collide. A
session is therefore fully isolated: it gets its *own database* (its own site
registry and results), not merely its own report folder. Mechanically a session
just supplies ``paths.output_root``; everything else falls out of the existing
output-relocation logic in :mod:`pdfscan.config.settings`.

The registry is a small user-level YAML file -- ``~/.pdfscan/sessions.yaml`` by
default, overridable with ``PDFSCAN_SESSIONS_FILE`` -- listing the known sessions
and which one is *active*. ``load_settings`` consults :func:`resolve_session_root`
during load; a selected session supplies ``output_root`` only when no explicit
output root was already given (yaml / ``--output-root`` / ``PDFSCAN_OUTPUT_ROOT``),
so those always win.

Selection precedence (highest first): ``--session`` / ``--session-root`` args >
``PDFSCAN_SESSION`` / ``PDFSCAN_SESSION_ROOT`` env > the registry's active session
> none (outputs stay in the project).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml


class SessionError(RuntimeError):
    """Raised for an unknown or invalid scan session (surfaced as a CLI error)."""


@dataclass(frozen=True)
class SessionRecord:
    """One registered workspace: a name pointing at an output root."""

    name: str
    root: Path
    label: str | None = None
    notes: str | None = None
    created_at: str | None = None


def default_sessions_path() -> Path:
    """Registry location: ``PDFSCAN_SESSIONS_FILE`` env, else ``~/.pdfscan/sessions.yaml``."""
    env = os.environ.get("PDFSCAN_SESSIONS_FILE")
    return Path(env).expanduser() if env else Path.home() / ".pdfscan" / "sessions.yaml"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _norm_root(value: str | os.PathLike) -> Path:
    """Normalize a workspace root to an absolute, ``~``-expanded path."""
    p = Path(value).expanduser()
    return p if p.is_absolute() else (Path.cwd() / p).resolve()


def _record_to_dict(rec: SessionRecord) -> dict[str, str]:
    data: dict[str, str] = {"root": str(rec.root)}
    if rec.label:
        data["label"] = rec.label
    if rec.notes:
        data["notes"] = rec.notes
    if rec.created_at:
        data["created_at"] = rec.created_at
    return data


class SessionRegistry:
    """The set of known sessions plus the active selection, backed by a YAML file.

    Mutations (:meth:`add` / :meth:`remove` / :meth:`use`) update the in-memory
    state only; call :meth:`save` to persist. ``active`` is normalized to ``None``
    whenever it does not name a known session (e.g. a stale or hand-edited file).
    """

    def __init__(
        self, path: Path, active: str | None, sessions: dict[str, SessionRecord]
    ) -> None:
        self.path = path
        self._sessions = sessions
        self.active = active if active in sessions else None

    # -- queries ----------------------------------------------------------------
    def get(self, name: str) -> SessionRecord | None:
        return self._sessions.get(name)

    def list(self) -> list[SessionRecord]:
        return [self._sessions[name] for name in sorted(self._sessions)]

    def active_record(self) -> SessionRecord | None:
        return self._sessions.get(self.active) if self.active else None

    # -- mutations (persist with save()) ----------------------------------------
    def add(
        self,
        name: str,
        root: str | os.PathLike,
        *,
        label: str | None = None,
        notes: str | None = None,
        activate: bool = False,
        created_at: str | None = None,
    ) -> SessionRecord:
        """Register (or update) a session. Re-adding keeps the original ``created_at``
        and preserves any label/notes not being overwritten."""
        name = (name or "").strip()
        if not name:
            raise SessionError("session name must not be empty")
        existing = self._sessions.get(name)
        rec = SessionRecord(
            name=name,
            root=_norm_root(root),
            label=label if label is not None else (existing.label if existing else None),
            notes=notes if notes is not None else (existing.notes if existing else None),
            created_at=(existing.created_at if existing else None) or created_at or _now(),
        )
        self._sessions[name] = rec
        if activate:
            self.active = name
        return rec

    def remove(self, name: str) -> bool:
        if name not in self._sessions:
            return False
        del self._sessions[name]
        if self.active == name:
            self.active = None
        return True

    def use(self, name: str | None) -> None:
        """Set (``name``) or clear (``None``) the active session."""
        if name is not None and name not in self._sessions:
            raise SessionError(
                f"unknown scan session '{name}'. List sessions with: pdfscan session list"
            )
        self.active = name

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "active": self.active,
            "sessions": {rec.name: _record_to_dict(rec) for rec in self.list()},
        }
        self.path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def load_sessions(path: str | os.PathLike | None = None) -> SessionRegistry:
    """Load the session registry (``path`` or the default). Missing file -> empty."""
    p = Path(path).expanduser() if path else default_sessions_path()
    if not p.exists():
        return SessionRegistry(p, active=None, sessions={})
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    sessions: dict[str, SessionRecord] = {}
    for name, body in (data.get("sessions") or {}).items():
        if not isinstance(body, dict) or not body.get("root"):
            continue  # skip malformed / root-less entries defensively
        sessions[str(name)] = SessionRecord(
            name=str(name),
            root=Path(str(body["root"])).expanduser(),
            label=body.get("label"),
            notes=body.get("notes"),
            created_at=body.get("created_at"),
        )
    return SessionRegistry(p, active=data.get("active"), sessions=sessions)


def _lookup(name: str) -> tuple[str, Path]:
    rec = load_sessions().get(name)
    if not rec:
        raise SessionError(
            f"unknown scan session '{name}'. List sessions with: pdfscan session list"
        )
    return rec.name, rec.root


def resolve_session_root(
    *, name: str | None = None, root: str | os.PathLike | None = None
) -> tuple[str | None, Path | None]:
    """Resolve the active workspace for this run -> ``(session_name, output_root)``.

    Returns ``(None, None)`` when no session applies (outputs stay in the project).
    An ad-hoc ``root`` (or ``PDFSCAN_SESSION_ROOT``) yields ``(None, <root>)`` -- it
    relocates outputs without a registered name. Raises :class:`SessionError` when a
    *named* session (arg or ``PDFSCAN_SESSION``) is not in the registry.
    """
    # 1. explicit arguments win (ad-hoc root is the most concrete)
    if root:
        return None, _norm_root(root)
    if name:
        return _lookup(name)
    # 2. environment
    env_root = os.environ.get("PDFSCAN_SESSION_ROOT")
    if env_root:
        return None, _norm_root(env_root)
    env_name = os.environ.get("PDFSCAN_SESSION")
    if env_name:
        return _lookup(env_name)
    # 3. the registry's active session
    rec = load_sessions().active_record()
    return (rec.name, rec.root) if rec else (None, None)
