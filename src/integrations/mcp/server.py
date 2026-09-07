"""Official MCP SDK server; transport is independent of runtime adaptation."""

from __future__ import annotations

import anyio
from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
)

from tool_runtime import ToolRuntime, build_default_tool_runtime

from .context_provider import ToolContextProvider
from .tool_adapter import MCPToolAdapter


SERVER_INSTRUCTIONS = (
    "GXWorks tools inspect the configured saved PLC project through ToolRuntime. "
    "patch_program and import_current_program_to_gxworks2 only return "
    "confirmation_required requests; they do not commit or import. "
    "This standalone server has no approval or desktop bridge. "
    "Report pending actions as pending and never claim they were executed. "
    "Read current project/program information before proposing a change. "
    "No physical PLC writes or low-level desktop controls are exposed."
)


def create_server(
    context_provider: ToolContextProvider, runtime: ToolRuntime | None = None
) -> Server:
    adapter = MCPToolAdapter(
        runtime if runtime is not None else build_default_tool_runtime(), context_provider
    )
    limiter = anyio.CapacityLimiter(1)

    async def list_tools(
        ctx: ServerRequestContext, params: PaginatedRequestParams | None
    ) -> ListToolsResult:
        return ListToolsResult(tools=adapter.list_tools())

    async def call_tool(
        ctx: ServerRequestContext, params: CallToolRequestParams
    ) -> CallToolResult:
        return await anyio.to_thread.run_sync(
            adapter.call_tool, params.name, params.arguments, str(ctx.request_id),
            limiter=limiter,
        )

    return Server(
        "gxworks-agent", version="0.1.0", instructions=SERVER_INSTRUCTIONS,
        on_list_tools=list_tools, on_call_tool=call_tool,
    )


async def serve_stdio(context_provider: ToolContextProvider) -> None:
    # SDK v2 owns UTF-8 framing and diverts stray Python/native stdout to stderr.
    async with stdio_server() as (read_stream, write_stream):
        server = create_server(context_provider)
        await server.run(
            read_stream, write_stream, server.create_initialization_options()
        )
