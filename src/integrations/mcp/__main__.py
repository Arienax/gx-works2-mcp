"""Run with python -m integrations.mcp --stdio --workspace ... --project ..."""

import argparse
import logging
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path


class _StderrParser(argparse.ArgumentParser):
    def _print_message(self, message, file=None):
        super()._print_message(message, sys.stderr)


def main(argv=None) -> int:
    parser = _StderrParser(description="GXWorks Agent MCP server (Python 3.10+).")
    parser.add_argument(
        "--stdio", action="store_true",
        help="Use stdio (the default and only transport).",
    )
    parser.add_argument(
        "--workspace", type=Path,
        default=os.environ.get("PLC_AI_WORKSPACE_DIR", "").strip() or None,
        help="Existing SessionStore workspace; defaults to PLC_AI_WORKSPACE_DIR.",
    )
    parser.add_argument("--project", required=True, help="Saved project ID.")
    parser.add_argument(
        "--version", help="Pin a version ID; otherwise follow the saved active version."
    )
    args = parser.parse_args(argv)
    if args.workspace is None:
        parser.error("--workspace or PLC_AI_WORKSPACE_DIR is required")
    if sys.version_info < (3, 10):
        parser.error("MCP requires Python 3.10+ in a separate environment from the Win7 desktop")
    logging.basicConfig(
        level=logging.INFO, stream=sys.stderr,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        # Keep import and setup diagnostics off the protocol stream as well.
        with redirect_stdout(sys.stderr):
            import anyio
            from .context_provider import SessionToolContextProvider
            from .server import serve_stdio

            provider = SessionToolContextProvider(args.workspace, args.project, args.version)
    except ImportError:
        parser.error("Install the optional dependencies: python -m pip install -r requirements-mcp.txt")
    except (OSError, ValueError) as error:
        parser.error(str(error))
    try:
        anyio.run(serve_stdio, provider)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
