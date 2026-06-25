"""Core service facade shared by the CLI, the MCP server, and the Skill."""

from pdfscan.service.facade import ScannerError, ScannerService

__all__ = ["ScannerService", "ScannerError"]
