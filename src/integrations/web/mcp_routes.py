"""Operator-only product onboarding routes for local MCP clients."""
from __future__ import annotations

from application.projects import public
from application.mcp_integrations import MCPIntegrationError
from . import responses as dto
from .schemas import MCPIntegrationCommand


def _connection_result(value, origin: str) -> dto.MCPIntegrationResult:
    # Project explicit public fields: generic credential/path redaction cannot
    # distinguish readiness flags and HTTP origins from secrets and file paths.
    return dto.MCPIntegrationResult(
        status=value["status"],
        project_id=value["project_id"],
        message=public(value["message"]),
        service_url=origin,
        tool_count=value["tool_count"],
        codex_connected=value.get("codex_connected"),
        replaced_existing=value.get("replaced_existing"),
    )


def register_mcp_routes(app, service, security) -> None:
    @app.get("/api/integrations/mcp", response_model=dto.MCPIntegrationStatus)
    def mcp_status(project_id: str):
        service.projects.project(project_id)
        from application.mcp_integrations import status
        value = status(project_id, security.origin)
        return dto.MCPIntegrationStatus(
            service_url=security.origin,
            project_id=value["project_id"],
            bound_project_id=value["bound_project_id"],
            credential_ready=value["credential_ready"],
            launcher_ready=value["launcher_ready"],
            codex_configured=value["codex_configured"],
            codex_cli_available=value["codex_cli_available"],
            codex_command=public(value["codex_command"]),
        )

    @app.post("/api/integrations/mcp/test", response_model=dto.MCPIntegrationResult,
              response_model_exclude_none=True)
    def mcp_test(command: MCPIntegrationCommand):
        service.writable()
        service.projects.project(command.project_id)
        from application.mcp_integrations import test_connection
        try:
            return _connection_result(test_connection(command.project_id, security.origin), security.origin)
        except MCPIntegrationError as error:
            return {"status": "failed", "message": public(str(error)), "project_id": command.project_id}

    @app.post("/api/integrations/mcp/codex/connect", response_model=dto.MCPIntegrationResult,
              response_model_exclude_none=True)
    def mcp_connect_codex(command: MCPIntegrationCommand):
        service.writable()
        service.projects.project(command.project_id)
        from application.mcp_integrations import connect_codex
        try:
            return _connection_result(connect_codex(command.project_id, security.origin), security.origin)
        except MCPIntegrationError as error:
            return {
                "status": "failed",
                "codex_connected": False,
                "message": public(str(error)),
                "project_id": command.project_id,
            }
