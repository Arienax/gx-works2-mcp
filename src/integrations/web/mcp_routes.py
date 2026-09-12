"""Operator-only product onboarding routes for local MCP clients."""
from __future__ import annotations

from application.projects import public
from application.mcp_integrations import MCPIntegrationError
from . import responses as dto
from .schemas import MCPIntegrationCommand


def register_mcp_routes(app, service, security) -> None:
    @app.get("/api/integrations/mcp", response_model=dto.PublicObject)
    def mcp_status(project_id: str):
        service.projects.project(project_id)
        from application.mcp_integrations import status
        return public(status(project_id, security.origin))

    @app.post("/api/integrations/mcp/test", response_model=dto.PublicObject)
    def mcp_test(command: MCPIntegrationCommand):
        service.writable()
        service.projects.project(command.project_id)
        from application.mcp_integrations import test_connection
        try:
            return public(test_connection(command.project_id, security.origin))
        except MCPIntegrationError as error:
            return {"status": "failed", "message": public(str(error)), "project_id": command.project_id}

    @app.post("/api/integrations/mcp/codex/connect", response_model=dto.PublicObject)
    def mcp_connect_codex(command: MCPIntegrationCommand):
        service.writable()
        service.projects.project(command.project_id)
        from application.mcp_integrations import connect_codex
        try:
            return public(connect_codex(command.project_id, security.origin))
        except MCPIntegrationError as error:
            return {
                "status": "failed",
                "codex_connected": False,
                "message": public(str(error)),
                "project_id": command.project_id,
            }
