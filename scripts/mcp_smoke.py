"""Offline initialize -> tools/list -> tools/call against the actual stdio CLI.

Run from any directory with a Python environment containing requirements-mcp.txt.
Creates and removes its own temporary SessionStore workspace. No desktop data,
GUI, GX Works2, simulator, PLC, API key, or network service is used.
"""

import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from plc_agent_tools import FORBIDDEN_TOOL_NAMES, SAFE_TOOL_NAMES
from plc_core import PLCCore
from plc_ir import build_plc_ir
from session_store import SessionStore


async def smoke() -> dict:
    with tempfile.TemporaryDirectory(prefix="gxworks-mcp-smoke-") as directory:
        store = SessionStore(base_dir=Path(directory) / "workspace")
        project = store.create_project("MCP smoke test")
        program = build_plc_ir({
            "device_comments": {"X0": "Start", "Y0": "Run"},
            "rungs": [{
                "rung_id": 1, "debug_note": "Read-only smoke fixture",
                "header_element": None, "shared_inputs": [],
                "branches": [{
                    "branch_id": 1, "y_offset_level": 0,
                    "inputs": [{"type": "NO", "address": "X0", "label": ""}],
                    "outputs": [{"type": "COIL", "address": "Y0", "label": ""}],
                }],
            }],
        }, plc_model="FX3U", revision=1)
        version_id, output_dir = store.prepare_version(project["id"])
        compiled = PLCCore().compile_project(program, output_dir)
        store.complete_version(project["id"], version_id, {
            **store._ir_metadata(program), "target_mode": "ladder", "plc_model": "FX3U",
            "artifacts": dict(compiled["artifacts"]),
        })
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "integrations.mcp", "--stdio", "--workspace", str(store.base_dir),
                  "--project", project["id"], "--version", version_id],
            cwd=ROOT / "src",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        with anyio.fail_after(25):
            async with stdio_client(parameters) as streams:
                async with ClientSession(*streams, read_timeout_seconds=10) as client:
                    initialized = await client.initialize()
                    tools = (await client.list_tools()).tools
                    names = {tool.name for tool in tools}
                    assert names == set(SAFE_TOOL_NAMES)
                    assert not names & FORBIDDEN_TOOL_NAMES
                    result = await client.call_tool("read_network", {"network_id": "N0001"})
                    assert not result.is_error
                    network = result.structured_content["data"]["network"]
                    assert network["writes"] == ["Y0"]
                    assert json.loads(result.content[0].text) == result.structured_content
                    return {
                        "ok": True,
                        "server": initialized.server_info.name,
                        "protocol_version": initialized.protocol_version,
                        "tool_count": len(tools),
                        "called_tool": "read_network",
                        "network_id": network["id"],
                    }


if __name__ == "__main__":
    print(json.dumps(anyio.run(smoke), ensure_ascii=False))
