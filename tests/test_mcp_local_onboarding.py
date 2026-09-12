"""Local MCP onboarding stays model-free and never exposes the Agent secret."""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace


def test_windows_service_binding_roundtrip(monkeypatch):
    from integrations.mcp import service_credentials as credentials

    store = {}
    fake = SimpleNamespace(
        write_api_key=lambda value, target: store.__setitem__(target, value),
        read_api_key=lambda target: store.get(target, ""),
        delete_api_key=lambda target: store.pop(target, None),
    )
    monkeypatch.setitem(sys.modules, "credential_store", fake)
    monkeypatch.setattr(credentials.os, "name", "nt")

    assert credentials.save_service_binding("http://127.0.0.1:8765", "agent-secret")
    saved = credentials.load_service_binding()
    assert saved == {
        "version": 1,
        "service_url": "http://127.0.0.1:8765",
        "agent_token": "agent-secret",
        "project_id": None,
    }
    public = credentials.bind_project("project_123")
    assert public == {"service_url": "http://127.0.0.1:8765", "project_id": "project_123"}
    assert credentials.load_service_binding()["project_id"] == "project_123"
    credentials.clear_service_binding("http://127.0.0.1:8765", "wrong")
    assert credentials.load_service_binding() is not None
    credentials.clear_service_binding("http://127.0.0.1:8765", "agent-secret")
    assert credentials.load_service_binding() is None


def test_launcher_check_uses_saved_service_and_bound_project(monkeypatch, capsys):
    from integrations.mcp import __main__ as launcher
    import integrations.mcp.service_credentials as credentials
    import integrations.mcp.service_client as service_client

    monkeypatch.setattr(credentials, "load_service_binding", lambda: {
        "version": 1,
        "service_url": "http://127.0.0.1:8765",
        "agent_token": "private-agent-token",
        "project_id": "project_abc",
    })

    class Client:
        def __init__(self, url, token):
            assert url == "http://127.0.0.1:8765"
            assert token == "private-agent-token"

        def list_tools(self):
            return [{"function": {"name": "get_current_project", "parameters": {"type": "object"}}}]

    monkeypatch.setattr(service_client, "ApplicationServiceClient", Client)
    assert launcher.main(["--check"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "ok": True,
        "service_url": "http://127.0.0.1:8765",
        "project_id": "project_abc",
        "tool_count": 1,
    }


def test_codex_connect_restores_config_when_add_fails(monkeypatch, tmp_path):
    import application.mcp_integrations as integrations

    config = tmp_path / ".codex" / "config.toml"
    config.parent.mkdir()
    original = b"[mcp_servers.old]\ncommand='old'\n"
    config.write_bytes(original)
    monkeypatch.setattr(integrations, "_codex_config_path", lambda: config)
    monkeypatch.setattr(integrations, "_codex_executable", lambda: "codex")
    monkeypatch.setattr(integrations, "launcher_invocation", lambda: ["gxworks-agent-mcp.exe"])
    monkeypatch.setattr(integrations, "test_connection", lambda project_id, service_url: {
        "status": "connected", "project_id": project_id, "service_url": service_url, "tool_count": 12,
    })

    def run(parts, timeout=15.0):
        if parts[1:4] == ["mcp", "add", "gxworks"]:
            config.write_text("broken", encoding="utf-8")
            return SimpleNamespace(returncode=1, stdout="", stderr="failed")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(integrations, "_run", run)
    try:
        integrations.connect_codex("project_abc", "http://127.0.0.1:8765")
    except integrations.MCPIntegrationError:
        pass
    else:
        raise AssertionError("failed Codex registration must surface an error")
    assert config.read_bytes() == original


def test_integrations_ui_does_not_require_token_copy():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "web" / "src" / "features" / "Settings.tsx").read_text(encoding="utf-8")
    assert "<paste PLC_WEB_AGENT_TOKEN>" not in text
    assert "连接 Codex" in text and "/integrations/mcp/codex/connect" in text
    assert "测试 MCP 连接" in text and "/integrations/mcp/test" in text
