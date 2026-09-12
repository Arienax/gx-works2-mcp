"""GXWorks Agent MCP launcher.

Normal Web users connect through the running local application service.  The
SessionStore reader remains available as an explicit --standalone/headless mode.
"""

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
        help="Use stdio (the current MCP transport and default).",
    )
    parser.add_argument(
        "--standalone", action="store_true",
        help="Advanced/headless mode: read an existing SessionStore directly instead of the running Web service.",
    )
    parser.add_argument(
        "--workspace", type=Path,
        default=os.environ.get("PLC_AI_WORKSPACE_DIR", "").strip() or None,
        help="Standalone only: existing SessionStore workspace; defaults to PLC_AI_WORKSPACE_DIR.",
    )
    parser.add_argument("--project", required=True, help="Saved/current project ID.")
    parser.add_argument(
        "--version", help="Pin a version ID; otherwise follow the saved/current active version."
    )
    parser.add_argument(
        "--service-url",
        default=os.environ.get("GXWORKS_AGENT_SERVICE_URL", "").strip() or "http://127.0.0.1:8765",
        help="Web service origin. Normal mode defaults to http://127.0.0.1:8765 or GXWORKS_AGENT_SERVICE_URL.",
    )
    parser.add_argument(
        "--service-token-env",
        default=os.environ.get("GXWORKS_AGENT_TOKEN_ENV", "").strip() or "PLC_WEB_AGENT_TOKEN",
        help="Environment variable containing the Web service agent token (default: PLC_WEB_AGENT_TOKEN).",
    )
    args = parser.parse_args(argv)
    if args.standalone and args.workspace is None:
        parser.error("--standalone requires --workspace or PLC_AI_WORKSPACE_DIR")
    if args.standalone and ("--service-url" in (argv or ()) or "--service-token-env" in (argv or ())):
        parser.error("--standalone cannot be combined with service connection options")
    if not args.standalone and not os.environ.get(args.service_token_env, "").strip():
        parser.error(
            f"Normal Web-service mode requires agent token environment variable {args.service_token_env}. "
            "Use --standalone only for advanced/headless SessionStore access."
        )
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
            if args.standalone:
                from .context_provider import SessionToolContextProvider
                from .server import serve_stdio

                provider = SessionToolContextProvider(args.workspace, args.project, args.version)
                runner, runner_args = serve_stdio, (provider,)
            else:
                from .service_client import ApplicationServiceClient, ServiceMCPToolAdapter
                from .server import serve_service_stdio

                client = ApplicationServiceClient.from_environment(args.service_url, args.service_token_env)
                # Validate identifiers before the stdio protocol starts.
                ServiceMCPToolAdapter(client, args.project, args.version)
                runner, runner_args = serve_service_stdio, (client, args.project, args.version)
    except ImportError:
        parser.error("Install the optional dependencies: python -m pip install -r requirements/mcp.txt")
    except (OSError, ValueError) as error:
        parser.error(str(error))
    try:
        anyio.run(runner, *runner_args)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
