# Integration onboarding

The Web workbench is the normal integration entry point. Existing `modelProfiles`,
`ModelProvider`, `ToolRuntime` and MCP tool schemas remain the source of truth.

## Source checkout quick start

On Windows, `build-web.bat` prepares the complete source Web runtime by default:
it creates `.venv` with Python 3.10+ when needed, installs
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

Select a project, then open **Settings → Model → Integrations / MCP** to connect
Codex. Keep the workbench running while using its engineering tools.

At Web startup the application creates a credential separate from the operator
login token and stores the current loopback MCP service record in Windows
Credential Manager. The record contains the loopback service origin, the
unprivileged Agent token and the currently bound project id. It is private to the
local process/user boundary and is never returned to the browser or written into
the PLC workspace.

In **Integrations / MCP**:

1. **测试 MCP 连接** binds the currently selected project and executes the real
   product launcher with `--check`. A successful result proves that launcher
   discovery, local credential lookup, Agent authentication and tool discovery
   all work.
2. **连接 Codex** performs the same check, then atomically adds or replaces only
   the `[mcp_servers.gxworks]` table in the user's Codex `config.toml`. Model
   selection/provider settings, project trust entries and every other MCP server
   are left unchanged. This does not require the Codex CLI to be in `PATH`.
3. In Codex, describe the task and its input/output behavior, for example:
   `使用 gxworks 为当前工程编写启停控制：X0 启动、X1 停止、Y0 控制电机，停止优先。`
   Review the program, change summary and pending approvals in the workbench.

The normal launcher therefore needs no user-facing URL, token, workspace or
Python path:

```text
gxworks-agent-mcp
```

The Windows Web release builds `gxworks-agent-mcp.exe` beside
`GXWorks-Agent-Web.exe`. Source checkouts use the same product entry internally
through the source `.venv`; the Web onboarding action writes the correct absolute
launcher invocation to Codex automatically.

The selected project binding is preserved across Web restarts when that project
still exists in the reopened workspace. Opening another workspace never blindly
reuses a project id that is absent there.

## Advanced / other clients

Claude, Cursor and other stdio MCP clients can use the same launcher. Bind the
current project once with **测试 MCP 连接**, then configure the client to start
`gxworks-agent-mcp`. Environment variables and explicit `--service-url` remain
available for automation and non-Windows development, but are not part of the
normal Windows user path.

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
