# GXWorks Agent

[简体中文](README.zh-CN.md)

An AI-assisted engineering workbench for Mitsubishi FX PLCs. The built-in agent
generates ladder or ST programs from natural-language requirements, with local
deterministic checks for instructions, devices, I/O, timing and program structure.
External MCP clients can use the existing engineering tools through the same
ToolRuntime.

## Capabilities

- PLC generation, version management, diffs, reviews and debugging
- GX Works2 program/device-comment CSV import/export and bidirectional sync
- GX Simulator2 regression workflows and readable test reports
- Local FX3U manual retrieval, model tool calls and image requirements
- DeepSeek, Zhipu and custom OpenAI-compatible model profiles

| Integration | Status | Scope |
| --- | --- | --- |
| Built-in agent | Working | ModelProvider and shared ToolRuntime |
| Standalone MCP server | **Working** | stdio discovery/calls against saved project snapshots; unit tests and actual process smoke test pass |
| Codex as an MCP client | Configuration example included | Same server and tools; no Codex-specific PLC logic |
| Streamable HTTP / desktop context bridge | Planned | Not exposed by the current CLI |
| Codex Harness / App Server | **Planned** | Not implemented |

Candidate patches and GX import tools return `confirmation_required`. The
standalone server has no approval execution or delivery to the desktop UI.
Low-level desktop control, unrestricted PLC writes and device forcing are not
exposed.

## Run the MCP server

Use a separate Python 3.10+ environment. From the checkout root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-mcp.txt
$env:PYTHONPATH = (Resolve-Path .\src).Path
.\.venv\Scripts\python.exe -m integrations.mcp --stdio --workspace '<existing-workspace>' --project '<project-id>'
```

See [MCP setup, context selection and safety](docs/integrations/mcp.md) and
[Codex configuration and the future harness boundary](docs/integrations/codex.md).
MCP dependencies are optional; `requirements.txt` and `requirements-win7.txt`
retain their desktop dependency sets. Real GX/Simulator workflows require the
corresponding Windows software; MCP unit tests and smoke tests do not.

```text
python -m pytest -q
python scripts/mcp_smoke.py
```

Run these in an environment with the relevant dependencies installed. The MCP
test module skips when its optional SDK is absent; the smoke test requires it.

## Technology

- Python, PyQt and PyInstaller
- Vendor-neutral ModelProvider, shared ToolRuntime and official Python MCP SDK
- PLC IR, static validators and deterministic SVG/CSV/ST rendering
- SQLite FTS5, BM25, dense vectors and hybrid reranking
- pywinauto, MX Component and a local C# simulator gateway

Desktop API keys remain in the current Windows user's Credential Manager, not
in source control. The standalone MCP server does not need a model API key.
