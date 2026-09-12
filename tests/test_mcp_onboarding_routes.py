"""Operator HTTP onboarding keeps readiness public and credentials private."""
from __future__ import annotations

import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi", reason="Web integration requires requirements/web.txt")
pytest.importorskip("httpx", reason="Web integration requires requirements/web.txt")
from fastapi.testclient import TestClient

from application.workbench import WorkbenchService
from test_web_api import AGENT, ORIGIN, _app, _login


@pytest.fixture
def onboarding(tmp_path, monkeypatch):
    import application.mcp_integrations as integrations
    from integrations.mcp import service_credentials as credentials

    secrets = {}
    monkeypatch.setitem(sys.modules, "windows_credentials", SimpleNamespace(
        write_secret=lambda value, target: secrets.__setitem__(target, value),
        read_secret=lambda target: secrets.get(target, ""),
        delete_secret=lambda target: secrets.pop(target, None),
    ))
    monkeypatch.setattr(credentials, "_is_windows", lambda: True)
    config = tmp_path / "codex" / "config.toml"
    monkeypatch.setattr(integrations, "_codex_config_path", lambda: config)
    monkeypatch.setattr(integrations, "_codex_executable", lambda: None)
    invocation = [str(tmp_path / "product" / "gxworks-agent-mcp.exe")]
    monkeypatch.setattr(integrations, "launcher_invocation", lambda: invocation)
    launches = []

    def check(parts, **kwargs):
        launches.append(parts)
        assert parts == invocation + ["--check"]
        return subprocess.CompletedProcess(parts, 0, json.dumps({
            "ok": True, "project_id": credentials.load_service_binding()["project_id"], "tool_count": 12,
        }), "")

    monkeypatch.setattr(integrations, "_run", check)
    service = WorkbenchService(tmp_path / "workspace", tmp_path / "state",
        model_factory=lambda: pytest.fail("Onboarding must not call a model"))
    project = service.store.create_project("HTTP onboarding")
    credentials.save_service_binding(ORIGIN, "isolated-onboarding-agent-secret")
    app = _app(service.store.base_dir, service.state_dir, service=service)
    with TestClient(app, base_url=ORIGIN) as client:
        yield SimpleNamespace(client=client, headers=_login(client), service=service, project=project["id"],
            integrations=integrations, credentials=credentials, secrets=secrets, config=config, launches=launches)


def test_ready_http_status_preserves_boolean_and_origin_without_codex_cli(onboarding):
    env = onboarding
    response = env.client.get("/api/integrations/mcp", params={"project_id": env.project})
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["credential_ready"] is True
    assert value["service_url"] == ORIGIN
    assert value["launcher_ready"] is True
    assert value["codex_cli_available"] is False
    assert value["codex_command"] is None
    assert env.launches == [] and not env.config.exists()
    assert "isolated-onboarding-agent-secret" not in response.text
    assert "agent_token" not in response.text


def test_http_connect_writes_only_temporary_config_without_codex_cli(onboarding):
    env = onboarding
    response = env.client.post("/api/integrations/mcp/codex/connect",
        json={"project_id": env.project}, headers=env.headers)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["status"] == "connected" and value["codex_connected"] is True
    assert value["service_url"] == ORIGIN
    assert value["tool_count"] == 12
    assert len(env.launches) == 1
    assert env.credentials.load_service_binding()["project_id"] == env.project
    config = env.config.read_text(encoding="utf-8")
    assert "[mcp_servers.gxworks]" in config and "gxworks-agent-mcp.exe" in config
    assert "isolated-onboarding-agent-secret" not in config + response.text
    assert "agent_token" not in config + response.text


def test_http_connection_test_preserves_origin_and_binding(onboarding):
    env = onboarding
    response = env.client.post("/api/integrations/mcp/test", json={"project_id": env.project}, headers=env.headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "connected"
    assert response.json()["service_url"] == ORIGIN
    assert response.json()["project_id"] == env.project
    assert env.credentials.load_service_binding()["project_id"] == env.project
    assert len(env.launches) == 1 and not env.config.exists()


@pytest.mark.parametrize("method,path,operation", [
    ("GET", "/api/integrations/mcp", "status"),
    ("POST", "/api/integrations/mcp/test", "test_connection"),
    ("POST", "/api/integrations/mcp/codex/connect", "connect_codex"),
])
def test_http_onboarding_projects_only_safe_fields(onboarding, monkeypatch, method, path, operation):
    env = onboarding
    original = getattr(env.integrations, operation)
    private_path = r"C:\private\onboarding\config.toml"

    def injected(*args, **kwargs):
        value = original(*args, **kwargs)
        value.update({"agent_token": "injected-agent-token", "credentials": {"password": "injected-password"},
            "_private_payload": {"secret": "injected-secret"}, "private_path": private_path,
            "credential_file": private_path})
        if method == "POST":
            value["message"] = "Connected; diagnostic file " + private_path
        return value

    monkeypatch.setattr(env.integrations, operation, injected)
    response = (env.client.get(path, params={"project_id": env.project}) if method == "GET" else
        env.client.post(path, json={"project_id": env.project}, headers=env.headers))
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["service_url"] == ORIGIN
    if method == "GET":
        assert value["credential_ready"] is True
    for secret in ("injected-agent-token", "injected-password", "injected-secret", private_path,
                   "isolated-onboarding-agent-secret"):
        assert secret not in json.dumps(value, ensure_ascii=False)
    for key in ("agent_token", "credentials", "_private_payload", "private_path", "credential_file"):
        assert key not in value
    if method == "POST":
        assert "[private path]" in value["message"]


def test_absent_local_binding_remains_explicitly_not_ready(onboarding):
    env = onboarding
    env.secrets.clear()
    response = env.client.get("/api/integrations/mcp", params={"project_id": env.project})
    assert response.status_code == 200, response.text
    assert response.json()["credential_ready"] is False
    assert response.json()["service_url"] == ORIGIN
    assert response.json()["bound_project_id"] is None
    assert env.launches == []


@pytest.mark.parametrize("path", ["/api/integrations/mcp/test", "/api/integrations/mcp/codex/connect"])
def test_wrong_service_binding_stays_failed_and_does_not_launch(onboarding, path):
    env = onboarding
    env.credentials.save_service_binding("http://127.0.0.1:8766", "other-service-agent-secret", "original-project")
    before = dict(env.secrets)
    status = env.client.get("/api/integrations/mcp", params={"project_id": env.project})
    assert status.json()["credential_ready"] is False
    response = env.client.post(path, json={"project_id": env.project}, headers=env.headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "failed"
    if path.endswith("/connect"):
        assert response.json()["codex_connected"] is False
    assert env.secrets == before and env.launches == [] and not env.config.exists()


@pytest.mark.parametrize("path", ["/api/integrations/mcp/test", "/api/integrations/mcp/codex/connect"])
def test_failed_connection_keeps_failure_response_and_redacts_paths(onboarding, monkeypatch, path):
    env = onboarding
    def fail(*args, **kwargs):
        raise env.integrations.MCPIntegrationError(r"Connection failed at C:\private\onboarding\trace.log")
    monkeypatch.setattr(env.integrations, "test_connection", fail)
    response = env.client.post(path, json={"project_id": env.project}, headers=env.headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "failed"
    assert "[private path]" in response.json()["message"]
    assert "trace.log" not in response.text
    if path.endswith("/connect"):
        assert response.json()["codex_connected"] is False
    assert env.launches == [] and not env.config.exists()


@pytest.mark.parametrize("path", ["/api/integrations/mcp/test", "/api/integrations/mcp/codex/connect"])
def test_operator_only_onboarding_preserves_csrf_origin_and_read_only_checks(onboarding, path):
    env = onboarding
    body = {"project_id": env.project}
    assert env.client.post(path, json=body).status_code == 403
    assert env.client.post(path, json=body, headers={**env.headers, "Origin": "https://other.example"}).status_code == 403
    assert env.client.post(path, json=body, headers={**env.headers, "Host": "other.example"}).status_code == 403
    env.service.read_only = True
    assert env.client.post(path, json=body, headers=env.headers).status_code == 403
    env.service.read_only = False
    env.client.cookies.clear()
    assert env.client.post(path, json=body, headers={"Origin": ORIGIN, "Authorization": "Bearer " + AGENT}).status_code == 401
    assert env.client.get("/api/integrations/mcp", params=body, headers={"Authorization": "Bearer " + AGENT}).status_code == 401
    assert env.launches == [] and not env.config.exists()
