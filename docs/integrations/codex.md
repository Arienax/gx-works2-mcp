# Codex integration

## Recommended: connect from the Web workbench

For normal Windows use, do not paste MCP TOML into Codex and do not ask Codex to
inspect this repository to discover how GXWorks MCP should be started.

1. Start GXWorks Agent Web and open the target project.
2. Open **Settings → Model → Integrations / MCP**.
3. Click **测试 MCP 连接**. This binds the selected project and verifies the
   actual product launcher, Windows Credential Manager lookup, Agent
   authentication and tool discovery.
4. Click **连接 Codex**. GXWorks Agent registers/replaces the fixed `gxworks`
   MCP entry through the local Codex CLI. The complete prior Codex config is
   restored if registration fails.
5. In Codex, ask for the engineering task directly, for example:

> 用 gxworks 给当前工程生成一个三菱起保停程序：X0 启动，X1 停止，Y0 电机，自锁。

The Web process stores the loopback service origin and its separate,
unprivileged Agent credential in Windows Credential Manager. The MCP launcher
therefore needs no user-facing `PLC_WEB_AGENT_TOKEN`, `--service-url`, project
path, `PYTHONPATH` or `python -m integrations.mcp` configuration. The selected
project binding is also retained across Web restarts when that project still
exists in the reopened workspace.

The effective normal path is:

```text
Codex
  -> gxworks-agent-mcp
  -> local Web service bridge
  -> ToolRuntime
  -> PLC Core
```

The launcher is model-independent. Replacing the model inside the Codex harness
with another Codex-compatible provider does not require a separate GXWorks MCP
implementation.

## What Codex should do after connection

The MCP server publishes its own operating instructions during initialization.
For a first ladder program the intended call sequence is:

```text
get_generation_context
-> optional search_plc_manual
-> create_program_candidate
```

For an existing ladder program:

```text
get_current_program_info
-> read_network
-> patch_program
```

Codex performs the model/planning role. GXWorks MCP and PLC Core perform the
deterministic engineering work. `create_program_candidate`, `patch_program` and
GX import requests preserve the existing engineering confirmation boundary. An
MCP tool approval is not permission to bypass Web proposal/approval semantics.

A successful generated candidate is reported as `confirmation_required`: it has
passed the deterministic candidate checks and temporary compilation, but it has
not thereby been written to a PLC or silently accepted into GX Works2.

## Product launcher

The Windows Web release places `gxworks-agent-mcp.exe` beside
`GXWorks-Agent-Web.exe`. Source mode uses the same launcher entry internally
through the source `.venv`; the Web onboarding action writes the correct absolute
invocation to Codex, so users do not need to know the Python module layout.

A diagnostic connection check is available without starting MCP stdio:

```text
gxworks-agent-mcp --check
```

It returns only the local service URL, bound project id and discovered tool count;
it never prints the Agent credential.

## Advanced / headless

Direct SessionStore mode remains for CI, isolated tests and environments where
no Web workbench is running:

```text
gxworks-agent-mcp --standalone --workspace <workspace> --project <project-id>
```

An explicitly supplied legacy `--workspace` still selects standalone mode for
backward compatibility. New integrations should use `--standalone` explicitly.

Environment-driven service configuration also remains available for automation:
`GXWORKS_AGENT_SERVICE_URL` (or `--service-url`) plus the selected
`--service-token-env`. These are advanced escape hatches, not the normal Windows
onboarding path.

## Confirmation and safety

External agents discover the same allow-listed high-level PLC tools used by the
built-in Agent. MCP does not expose arbitrary filesystem deletion, mouse or
keyboard control, physical PLC writes or device-force primitives. Service-mode
candidates are persisted as proposals for the Web workbench; the Agent
credential cannot approve those proposals or call operator-only HTTP routes.

## Opposite integration direction: embedding Codex Harness

Hosting `codex app-server` inside GXWorks Agent is a separate integration
direction. It should remain an Agent backend with explicit ownership of
threads/turns, approval requests and streamed events rather than being squeezed
into `ModelProvider`. This onboarding work does not implement that future
`CodexHarnessBackend` and does not change `ToolRuntime` or the engineering tool
catalog.
