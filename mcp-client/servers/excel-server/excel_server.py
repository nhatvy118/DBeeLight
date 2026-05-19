"""Stdio entrypoint for the excel-mcp-server package.

The agent's ``connect_to_server`` only knows how to spawn ``.py`` / ``.js``
scripts. ``excel-mcp-server`` ships as a CLI (``uvx excel-mcp-server stdio``),
so we re-export its stdio runner from a tiny script the agent can launch.
"""

from excel_mcp.server import run_stdio


if __name__ == "__main__":
    run_stdio()
