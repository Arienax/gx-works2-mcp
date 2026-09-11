"""Context policy + actual refresh backend; only model replies are fixed."""
import copy
import json
from pathlib import Path
import pytest
import api
from fastapi.testclient import TestClient
from application.workbench import WorkbenchService
from prompt_context_policy import POLICY_NAMES, context_policy_scope, ContextAudit
from test_web_api import ORIGIN, _Provider, _app, _complete, _login, _ladder


@pytest.mark.parametrize("name", POLICY_NAMES)
def test_actual_backend_policy_audit_autosave_and_refresh(tmp_path, monkeypatch, name):
    monkeypatch.setenv("GXWORKS_CONTEXT_POLICY", name)
    # Keep prompt construction and local retrieval real; forbid remote fallback.
    monkeypatch.setattr(api, "load_full_config", lambda: {})
    monkeypatch.setattr(api, "get_active_provider", lambda: pytest.fail("Unexpected live provider"))
    provider = _Provider()
    service = WorkbenchService(tmp_path / "workspace", tmp_path / "state",
        model_factory=lambda: (provider, {"model": "offline-policy-check"}))
    with TestClient(_app(service.store.base_dir, service.state_dir, service=service), base_url=ORIGIN) as client:
        headers = _login(client)
        pid = client.post("/api/projects", json={"name": "Policy " + name}, headers=headers).json()["id"]
        service.store.set_confirmed_spec(pid, {"summary": "X0 controls Y0", "io_table": [], "parameters": []})
        jid, output = _complete(client, service, client.post("/api/jobs", headers=headers, json={
            "project_id": pid, "kind": "generation", "request_id": "context_" + name,
            "text": "X0 controls Y0", "response_language": "en"}))
        assert output.get("version_id") and output.get("proposal_id")
        assert len(provider.requests) == 1
        audit_events = [e for e in service.jobs.events(jid) if e["event_type"] == "context_audit"]
        assert audit_events and all(e["payload"]["policy"]["name"] == name for e in audit_events)
        assert all(e["payload"]["message_text_chars"] > 0 for e in audit_events)
        metadata = json.dumps(audit_events)
        assert "X0 controls Y0" not in metadata
        before_calls = len(provider.requests)
        before = {str(p): p.read_bytes() for p in (tmp_path / "workspace").rglob("*") if p.is_file()}
        for _ in range(2):
            response = client.get(f"/api/jobs/{jid}/preview")
            assert response.status_code == 200, response.text
            assert response.headers["cache-control"] == "no-store"
            assert "<svg" in response.json()["svg"]
        assert len(provider.requests) == before_calls
        assert service.projects.project(pid)["version_count"] == 1
        assert before == {str(p): p.read_bytes() for p in (tmp_path / "workspace").rglob("*") if p.is_file()}


@pytest.mark.parametrize("mode", ["ladder", "st"])
def test_actual_prompt_markers_and_fixed_profiles_across_arms(mode):
    spec = {"summary": "Only compare declared values", "io_table": [], "parameters": []}
    profiles = []
    for name in ("minimal", "manual", "examples", "combined", "adaptive"):
        audit = ContextAudit()
        with context_policy_scope(name, audit=audit):
            messages, _, _ = api._prepare_api_call("X0 controls Y0", "offline", "high", mode,
                confirmed_spec=copy.deepcopy(spec), plc_model="FX3U", persist_history=False)
        assert messages[0]["content"]
        sections = audit.snapshot()["pending_sections"]
        profiles.append(next(s["sha256"] for s in sections if s["section"] == "model_profile"))
        assert any(s["section"] == "base_prompt" and s["reason"] == "controlled_baseline" for s in sections)
    assert len(set(profiles)) == 1
