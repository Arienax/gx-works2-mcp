# Codex integration

## Recommended: connect from the Web workbench

The Windows Web workbench configures a local MCP connection for Codex App on
the same computer; installing Codex CLI is optional. MCP is the supported
engineering interface to GXWorks Agent and does not require a client skill.
Optional client guidance cannot replace the engineering platform, tool calls,
validation, saved project state or approval.

1. Start GXWorks Agent Web and open the target project.
2. Open **Settings → Model → Integrations / MCP**.
3. Click **连接 Codex**. This binds the selected project and verifies the product
   launcher, Windows Credential Manager lookup, Agent authentication and tool
   discovery. It atomically adds or replaces only the `[mcp_servers.gxworks]` table and its
   nested subtables in Codex `config.toml`. Existing model/provider settings,
   project trust entries and other MCP servers are preserved. Codex CLI does not
   need to be in `PATH`. **测试 MCP 连接** runs the service probe independently;
   it does not write Codex configuration.
4. After configuration completes, restart Codex App and create a new task to
   load the connection.
5. Describe the engineering task in Codex, for example:

> 用 gxworks 给当前工程生成一个三菱起保停程序：X0 启动，X1 停止，Y0 电机，自锁。

The client must discover and call the connected `gxworks` tools. The MCP server
supplies initialization instructions and tool descriptions for that workflow.
If no tool calls are recorded, check the gxworks MCP connection in Codex and
explicitly request gxworks tools in a new task. Check the workbench's actual
client activity to establish that MCP tools ran; a request alone is not evidence.

The configuration file is `$CODEX_HOME/config.toml` when `CODEX_HOME` is set,
otherwise `~/.codex/config.toml`.

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

## Reading connection status

The settings page separates three kinds of evidence:

- **Connection configuration:** whether the Codex MCP table is present. Its
  presence does not prove that a running client has loaded the connection.
- **MCP service check:** the result of a single launcher probe in the current
  settings session. A passing probe establishes service access and tool
  discovery at that time, not that the client invoked an engineering tool.
- **Client tool calls:** successful calls received through the Agent bridge for
  the selected project by this running Web service. `tools/list` and launcher
  probes do not count. Until a successful call arrives, the page shows
  **等待客户端调用**; afterwards it shows **客户端已调用**.

Client activity records the last tool name and call time, whether
`get_generation_context` has succeeded, and the latest proposal ID returned by
`create_program_candidate` or `patch_program`. It retains no tool arguments,
prompts or credentials. These summaries are in memory for the current service
instance and reset when the Web service restarts. The page refreshes them while
visible. They establish that a client used the service, but do not identify that
client as Codex App rather than another authorized MCP/Agent client. A proposal
ID is a reference to inspect, not proof of approval, a saved version, native
compilation or successful simulation.

## What Codex should do after connection

The MCP server's initialization instructions direct Codex to the shared
engineering tools. It should discover the enabled `gxworks` tools and call
`get_current_project` to confirm the bound PLC project and model.
For first generation and ordinary edits, use the same sequence:

```text
get_current_project
-> get_generation_context(user_requirement="current request")
-> client plans the full or partial ladder
-> search_plc_manual, if specific facts still need evidence
-> create_program_candidate
```

`get_generation_context` returns the API's shared `generation_instructions`,
`generation_request`, confirmed engineering specification, selected model and
current ladder context. It uses the same local RAG policy, budget and retrieval
fallback as the API. The optional request improves the context; empty arguments
remain supported. An empty PLC project is valid input, not a request to inspect
the Codex working directory or hand-write CSV files in the repository.

For an existing program, the shared output guidance prefers `mode="partial"`
with only changed/new complete rungs, comment updates and explicit deletions;
a full response remains accepted. Both forms use the same API compatibility
normalization, structural checks, IR construction and artifact renderer.
Unambiguous legacy OUT/timer/counter forms are normalized before checking;
unsupported instructions, invalid addresses and scope escapes still fail.
The server chooses `generation_structural` and carries it through proposal,
save and reload, so ordinary generation is not rejected again by a separate
MCP semantic policy. It does not call another model to reinterpret Codex's work.

Use the selected model and concrete instruction/timer terms with
`search_plc_manual` for unresolved device ranges, time bases and presets.
Irrelevant or empty results are not evidence; refine the search and report
unresolved facts when evidence remains unavailable. A failed candidate returns
its actual error; there is no automatic repeated-submission repair loop. Explicit Debug work remains a separate
`get_current_program_info → read_network → patch_program` workflow with its
existing scoped, strict checks.

The normalization summary records conditions removed or shared and adjacent
outputs combined, plus reasons for leaving a structure unchanged. It avoids
moving conditions across state changes or read-after-write dependencies and
does not merge repeated writes to the same coil into an OR. For edits it is
limited to submitted/changed networks. The workbench retains the summary with
the proposal and saved version; structural readiness and this summary do not
establish that the requested behavior has been tested.

Codex performs the model/planning role. GXWorks MCP and PLC Core perform the
deterministic engineering work. `create_program_candidate`, `patch_program` and
GX import requests preserve the existing engineering confirmation boundary. An
MCP tool approval is not permission to bypass Web proposal/approval semantics.

A `confirmation_required` result means a candidate passed the reported local
checks and requires handling according to the workbench's approval policy.
Service-mode calls may also return a saved `version_id` when that policy accepts
a local proposal; report that version only when the response supplies it.
Otherwise report the actual `project_id`, `proposal_id`, validation result and
remaining review steps. Neither a candidate nor a locally saved version proves
GX Works2 native compilation, simulation, import or physical PLC execution.
Report those as unverified unless the corresponding operation actually ran and
returned a result.

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

### Client guidance is independent

The Web connection wizard checks the MCP service and atomically updates the
Codex MCP configuration. It does not inspect, create, update or delete
`~/.agents` or user skill files. Existing custom skills remain untouched, and
missing or inaccessible skill directories do not block connection. Optional
client guidance is independent of MCP and is not proof of tool access or
engineering validation. If configuration cannot be written, setup reports a
failure rather than claiming the connection configuration is complete.

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
