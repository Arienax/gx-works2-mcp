# Codex integration

## A. Codex uses GXWorks Agent tools over MCP — implemented

```mermaid
flowchart LR
    Codex --> Client[MCP client]
    Client --> Server[GXWorks Agent MCP server]
    Server --> Runtime[ToolRuntime]
    Runtime --> Core[PLC Core and existing tool implementations]
```

Install the optional MCP environment and identify your saved workspace/project
as described in [MCP setup](mcp.md). Codex launches the same standalone server as
any other MCP client. No Codex-specific PLC implementation or model API key is
needed by that server.

Codex supports stdio server configuration in `~/.codex/config.toml` or a trusted
project's `.codex/config.toml`. Its `command`, `args`, `cwd` and `env` fields control
the subprocess. See the [official MCP configuration documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).

Windows example (replace each `<...>` placeholder; forward slashes avoid TOML
backslash escapes):

```toml
[mcp_servers.gxworks]
command = "<checkout>/.venv/Scripts/python.exe"
args = ["-m", "integrations.mcp", "--stdio", "--workspace", "<workspace>", "--project", "<project-id>"]
cwd = "<checkout>/src"
startup_timeout_sec = 30
tool_timeout_sec = 120
```

Use absolute paths for the actual checkout, Python executable and workspace.
The example contains no developer-specific path. Setting `cwd` to `src` lets
Python find both the adapter package and the repository's existing flat modules.
Append `"--version", "v0001"` to `args` to pin a saved version; otherwise calls
follow the saved active version. This does not follow unsaved GUI selection.

Generic configuration, for a compatible host with a copied saved workspace:

```toml
[mcp_servers.gxworks]
command = "<checkout>/.venv/bin/python"
args = ["-m", "integrations.mcp", "--stdio", "--workspace", "<workspace>", "--project", "<project-id>", "--version", "v0001"]
cwd = "<checkout>/src"
startup_timeout_sec = 30
tool_timeout_sec = 120
```

The generic form is provided for portability; this change was tested on Windows.
Live GX/Simulator integration remains Windows-specific.

Alternatively, PowerShell can register the command through Codex's CLI:

```powershell
$Checkout = (Resolve-Path .).Path
$McpPython = Join-Path $Checkout '.venv\Scripts\python.exe'
$Source = Join-Path $Checkout 'src'
$Workspace = '<existing SessionStore workspace directory>'
$ProjectId = '<saved project ID>'
codex mcp add gxworks --env "PYTHONPATH=$Source" -- $McpPython -m integrations.mcp --stdio --workspace $Workspace --project $ProjectId
codex mcp list
```

Use either the configuration file or CLI registration for this server. This
repository does not change your Codex configuration automatically. In Codex's
terminal UI, `/mcp` shows active MCP servers. These commands are documented in
the [official Codex MCP guide](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).

Try a read-only request:

> Use the gxworks MCP tools to read the current project and program information,
> then read network N0001 if it exists. Report the saved project and version IDs.

For patches or import requests, `confirmation_required` remains pending. The
standalone server cannot approve or deliver proposals to the desktop. Codex
approval of an MCP call does not approve the underlying engineering action.
See [confirmation semantics](mcp.md#confirmation-and-safety).

### Natural-language ladder generation

Codex can now design the first ladder program for the configured saved project,
including a project with no program versions. For first generation, omit a
`--version` argument that would point to a nonexistent version. Codex performs
the model role itself; GXWorks MCP and PLC Core perform the deterministic
engineering work. No DeepSeek/OpenAI-compatible ModelProvider or model API key
is used by the MCP server.

Example user request:

> Use the gxworks MCP tools to create a ladder program for the current project.
> X0 is Start, X1 is Stop, Y0 drives the motor.
> Use a seal-in circuit for Y0.
> Do not edit workspace files directly.

中文示例：

> 使用 gxworks MCP 为当前项目生成一个三菱梯形图：
> X0 启动，X1 停止，Y0 控制电机，Y0 使用自锁。
> 先读取生成上下文，不要直接编辑工程文件。
> 生成后通过 create_program_candidate 提交并校验。

Expected calls:

```text
get_generation_context
→ optional search_plc_manual
→ create_program_candidate
```

Codex reads the returned `output_contract`, confirmed specification, selected
approach, I/O assignments and hardware constraints before designing the program.
It generates only `device_comments` and `rungs`, in `ladder_v1` JSON, plus an
optional `program_name` (default `MAIN`). It does not generate full canonical IR.
Project identity, PLC model, confirmed specification, revision and candidate
identity/hashes are server-owned. The complete schemas and result fields are
documented in [initial ladder generation](mcp.md#initial-ladder-generation).

PLC Core runs the existing ladder validation, builds canonical IR at revision 1,
checks the IR and static diagnostics, and compiles artifacts in a temporary
directory. Validation errors are returned to Codex for correction. Retry at most
twice after the initial submission, then report unresolved errors or conflicting
requirements; do not silently replace the project's confirmed choices.

The successful result must be `status = confirmation_required`. A correct report
is: “候选程序已通过确定性校验和临时编译，等待工程确认；尚未保存或导入。”
Do not report “程序已经保存”, “程序已经写入 GX Works2” or “PLC 已经被修改”.
No official project version is created, `active_version_id` remains unchanged,
and neither GX Works2 import nor a physical PLC write occurs. Codex approval of
the MCP tool call does not approve the engineering candidate.

This standalone interface has no candidate accept/commit tool, retained approval
queue or desktop confirmation bridge. The candidate ID is an audit identifier,
not a token that can later be committed through MCP. Saving and desktop approval
delivery for these generated candidates remain unimplemented. Do not edit
workspace JSON files to work around this boundary. Existing-program edits
continue to use `get_current_program_info → read_network → patch_program`.

The server process was tested with the official MCP client, including actual
stdio discovery, read-only invocation and first-generation candidates. The
configuration examples are checked against the Codex documentation; a live Codex
session using the saved configuration is not part of the automated test suite.

## B. GXWorks Agent embeds Codex Harness / App Server — planned

This is the opposite integration direction: the workbench would host a Codex
agent session through `codex app-server`. It is not implemented by the MCP
adapter. The [official App Server interface](https://learn.chatgpt.com/docs/app-server)
includes threads, turns, approval requests and streamed agent events.

A future boundary could be:

```text
AgentBackend (future)
├── BuiltinAgentBackend
│   ├── ModelProvider
│   └── ToolRuntime
└── CodexHarnessBackend
    ├── Codex App Server
    └── GXWorks MCP tools → ToolRuntime
```

Treat App Server as an agent harness, with explicit ownership of threads/turns,
approvals, tool execution, filesystem/sandbox events and diffs. Do not squeeze it
into an OpenAI-compatible ModelProvider if that loses these semantics. A future
backend must coordinate engineering confirmations with the desktop while keeping
PLC logic in the shared runtime. No AgentBackend refactor, App Server process,
thread/event bridge or harness approval implementation is included in Phase 1.
