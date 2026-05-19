"""Filesystem locations of the MCP server scripts bundled with this package.

The actual server projects live under ``mcp-client/servers/<name>/`` so that
the ``mcp_agent`` client and its companion servers ship as a single unit.
"""
from __future__ import annotations

from pathlib import Path

SERVERS_DIR: Path = Path(__file__).resolve().parent.parent / "servers"

SERVER_SCRIPTS: dict[str, Path] = {
    "database": SERVERS_DIR / "database" / "database.py",
    "excel": SERVERS_DIR / "excel-server" / "excel_server.py",
    "gsheets": SERVERS_DIR / "gsheets-server" / "gsheets_server.py",
    "chart": SERVERS_DIR / "chart-server" / "chart_server.py",
}


def server_script(name: str) -> Path:
    """Return the absolute path of a bundled MCP server entrypoint."""
    try:
        return SERVER_SCRIPTS[name]
    except KeyError as exc:
        raise KeyError(
            f"Unknown MCP server '{name}'. Known: {sorted(SERVER_SCRIPTS)}"
        ) from exc


__all__ = ["SERVERS_DIR", "SERVER_SCRIPTS", "server_script"]
