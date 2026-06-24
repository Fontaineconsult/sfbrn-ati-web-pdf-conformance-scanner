"""Configuration loading: global settings and veraPDF ignore profiles."""

from pdfscan.config.ignore_profiles import IgnoreProfiles, load_ignore_profiles
from pdfscan.config.settings import Settings, load_settings

__all__ = ["Settings", "load_settings", "IgnoreProfiles", "load_ignore_profiles"]
