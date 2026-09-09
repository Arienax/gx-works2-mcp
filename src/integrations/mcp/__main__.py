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
    parser.add_argument(
        "--service-url", help="Explicit application-service mode: loopback HTTP origin."
    )
    parser.add_argument(
        "--service-token-env", help="Environment variable containing the service's agent token (never an operator token)."
    )
    args = parser.parse_args(argv)
    if args.service_url and not args.service_token_env:
        parser.error("--service-token-env is required with --service-url")
    if args.service_token_env and not args.service_url:
        parser.error("--service-token-env requires --service-url")
    if not args.service_url and args.workspace is None:
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
            if args.service_url:
                from .service_client import ApplicationServiceClient, ServiceMCPToolAdapter
                from .server import serve_service_stdio

                client = ApplicationServiceClient.from_environment(args.service_url, args.service_token_env)
                # Validate identifiers before the stdio protocol starts.
                ServiceMCPToolAdapter(client, args.project, args.version)
                runner, runner_args = serve_service_stdio, (client, args.project, args.version)
            else:
                from .context_provider import SessionToolContextProvider
                from .server import serve_stdio

                provider = SessionToolContextProvider(args.workspace, args.project, args.version)
                runner, runner_args = serve_stdio, (provider,)
    except ImportError:
        parser.error("Install the optional dependencies: python -m pip install -r requirements-mcp.txt")
    except (OSError, ValueError) as error:
        parser.error(str(error))
    try:
        anyio.run(runner, *runner_args)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
