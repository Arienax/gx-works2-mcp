"""Product MCP entry must hide the repository's internal Python module layout."""

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run(*args):
    env = {**os.environ, "PYTHONPATH": "", "PLC_AI_WORKSPACE_DIR": ""}
    env.pop("PLC_WEB_AGENT_TOKEN", None)
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "mcp_entry.py"), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        timeout=15,
    )


def test_product_entry_help_requires_no_pythonpath():
    result = _run("--help")
    assert result.returncode == 0
    assert result.stdout == b""
    assert b"GXWorks Agent MCP server" in result.stderr


def test_product_entry_defaults_to_web_service_and_requires_agent_token():
    result = _run("--project", "p1")
    assert result.returncode == 2
    assert result.stdout == b""
    assert b"PLC_WEB_AGENT_TOKEN" in result.stderr


def test_explicit_standalone_mode_requires_workspace():
    result = _run("--standalone", "--project", "p1")
    assert result.returncode == 2
    assert result.stdout == b""
    assert b"workspace" in result.stderr.lower()
