"""Configuration loading: global settings, veraPDF ignore + classification profiles."""

from pdfscan.config.ignore_profiles import IgnoreProfiles, load_ignore_profiles
from pdfscan.config.sessions import (
    SessionError,
    SessionRecord,
    SessionRegistry,
    load_sessions,
)
from pdfscan.config.settings import Settings, load_settings

__all__ = [
    "Settings",
    "load_settings",
    "IgnoreProfiles",
    "load_ignore_profiles",
    "SessionRegistry",
    "SessionRecord",
    "SessionError",
    "load_sessions",
    "ClassificationProfile",
    "load_classification_profile",
]


def __getattr__(name: str):
    # Lazy re-export to keep the classification profile reachable from
    # ``pdfscan.config`` (symmetry with ``load_ignore_profiles``) without a
    # module-load import edge config -> classify.
    if name in {"ClassificationProfile", "load_classification_profile"}:
        from pdfscan.classify import profile as _profile

        return getattr(_profile, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
