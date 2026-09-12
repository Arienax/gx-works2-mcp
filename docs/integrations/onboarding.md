# Integration onboarding

The Web workbench is the normal integration entry point. Existing `modelProfiles`,
`ModelProvider`, `ToolRuntime` and MCP tool schemas remain the source of truth.

## Source checkout quick start

On Windows, `build-web.bat` now prepares the complete source Web runtime by
default: it creates `.venv` with Python 3.10+ when needed, installs
`requirements/web.txt`, installs the locked frontend dependencies, regenerates
API types and builds `web/dist`. After a successful build, run `start-web.cmd`
directly from the repository root.

Use `build-web.bat --frontend-only` only when the Python backend environment is
managed separately. `start-web.cmd` prefers the extracted release executable,
then the source `.venv`, and can also fall back to a locally built
`dist/GXWorks-Agent-Web/GXWorks-Agent-Web.exe` package.

## Model API

Open **Settings → Model → Model API**. For an OpenAI-compatible service, enter
the API URL and key, then choose **自动获取模型 + 检测能力**. The workbench reads
the provider model list and performs bounded probes for tool calling and JSON
structured output. The discovered model can then be selected and saved as an
ordinary existing `modelProfile`.

Provider-specific capability flags, generation defaults and request overrides are
kept under **高级设置**. Detection is best-effort: it never silently removes an
existing known-good capability merely because an optional probe fails.

## MCP for Web users

Open **Settings → Model → Integrations / MCP** after selecting a project. The page
generates Codex, Claude and Cursor configuration using the selected project and
the current loopback Web origin.

Normal MCP startup is the Web service bridge:

```text
gxworks-agent-mcp --project <project-id> --service-url http://127.0.0.1:8765
```

The Web launcher creates a credential separate from the operator token. If
`PLC_WEB_AGENT_TOKEN` was not supplied before startup, the generated MCP agent
token is printed once in the Web launch terminal. Put that value in the MCP
client's `PLC_WEB_AGENT_TOKEN` environment entry. Do not use the operator login
token as an MCP credential.

The Windows Web release also builds `gxworks-agent-mcp.exe` beside
`GXWorks-Agent-Web.exe`; source checkouts provide `gxworks-agent-mcp.cmd` and a
portable launcher script. End users do not need to know the internal Python
module path or set `PYTHONPATH`.

## Advanced / headless

Direct SessionStore access is retained for CI, isolated tests and headless use:

```text
gxworks-agent-mcp --standalone --workspace <workspace> --project <project-id>
```

For compatibility, an explicitly supplied legacy `--workspace` also selects
standalone mode, but new integrations should use `--standalone` so the boundary
is obvious.

Only stdio MCP transport is changed by this onboarding work. Streamable HTTP is
not introduced here, and neither `ToolRuntime` nor the existing engineering tool
catalog is duplicated or rewritten.
