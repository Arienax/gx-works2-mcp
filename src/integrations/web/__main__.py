"""Single-worker local service launcher. Never start GX on page load."""
import argparse
import os
import secrets
import sys
import threading
from pathlib import Path
from urllib.parse import quote


def _open_when_started(server, login_url, stopped):
    """Open only after this server bound its port, never an unrelated listener."""
    import webbrowser

    while not stopped.wait(0.1):
        if server.started:
            try:
                if not webbrowser.open(login_url, new=2):
                    print("Browser did not open; use the Operator login link above.", file=sys.stderr)
            except Exception:
                print("Browser could not open; use the Operator login link above.", file=sys.stderr)
            return


def main(argv=None):
    parser = argparse.ArgumentParser(description="GXWorks Agent local web workbench")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--read-only", action="store_true")
    parser.add_argument("--open-browser", action="store_true", help="Open the operator login page once this service is ready.")
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error("Use a port from 1024 to 65535")
    from .app import create_app
    import uvicorn
    token = os.environ.get("PLC_WEB_OPERATOR_TOKEN") or secrets.token_urlsafe(32)
    origin = "http://127.0.0.1:" + str(args.port)
    app = create_app(args.workspace, state_dir=args.state_dir, read_only=args.read_only,
        origin=origin, operator_token=token, agent_token=os.environ.get("PLC_WEB_AGENT_TOKEN"))
    login_url = origin + "/#token=" + quote(token, safe="")
    print("Operator login (keep private): " + login_url, file=sys.stderr)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.port, workers=1, access_log=False))
    stopped = threading.Event()
    if args.open_browser:
        threading.Thread(target=_open_when_started, args=(server, login_url, stopped), daemon=True, name="web-login-launcher").start()
    try:
        server.run()
    finally:
        stopped.set()
    return 0 if server.started else 1


if __name__ == "__main__":
    raise SystemExit(main())
