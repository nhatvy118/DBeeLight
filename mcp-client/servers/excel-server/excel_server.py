"""Stdio entrypoint for the excel-mcp-server package.

The agent's ``connect_to_server`` only knows how to spawn ``.py`` / ``.js``
scripts. ``excel-mcp-server`` ships as a CLI (``uvx excel-mcp-server stdio``),
so we re-export its stdio runner from a tiny script the agent can launch.
"""

import sys

from excel_mcp.server import run_stdio

# Errors the OS/anyio raise when the parent closes the stdio pipe on us.
_TEARDOWN_ERRORS = (BrokenPipeError, ConnectionResetError, EOFError)


def _is_teardown_noise(exc: BaseException) -> bool:
    """True if ``exc`` is — or only wraps — expected stdio pipe-close errors.

    anyio bundles the real cause inside an ``ExceptionGroup`` (its ``.exceptions``
    attribute), so recurse into groups; a group that contains *anything* other
    than a pipe-close error is a genuine fault and must not be swallowed.
    """
    nested = getattr(exc, "exceptions", None)
    if nested is not None:  # ExceptionGroup / BaseExceptionGroup
        return all(_is_teardown_noise(e) for e in nested)
    return isinstance(exc, _TEARDOWN_ERRORS)


if __name__ == "__main__":
    # When the parent (mcp-client) closes the stdio connection — on idle-agent
    # eviction, disconnect, or app shutdown — the read end of our stdout is gone
    # while the stdio server is still flushing its final buffer. That surfaces as
    # a ``BrokenPipeError`` (often wrapped in an ``ExceptionGroup``). It is the
    # *expected* way this subprocess is told to stop, so exit cleanly instead of
    # dumping an alarming teardown traceback. Anything else still propagates.
    try:
        run_stdio()
    except BaseException as exc:
        if _is_teardown_noise(exc):
            sys.exit(0)
        raise
