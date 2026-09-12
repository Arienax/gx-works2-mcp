"""Native evidence must never imply automatic compilation or cross version bindings."""
import base64
from copy import deepcopy
import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from application.fbd import FBDValidationError
from application.native_validation import NativeValidationService
from application.workbench import WorkbenchService
from application.workspace import ConflictError
from gxw.object_model import generate_object_project
from tests.test_gxw_object_model import two_timers
from tests.test_web_fbd import service, generate, accept
from tests.test_web_api import _app, _login, ORIGIN


def command(digest, **updates):
    return {"request_id": "native-result", "source_gxw_sha256": digest, "operator": "工程师甲",
            "tool_version": "GX Works2 1.6xx", "outcome": "passed", "report": "模拟的操作员报告：编译完成，0 错误。",
            "attested": True, **updates}


def test_draft_preview_matches_candidate_without_creating_proposals_or_versions(service):
    project = service.create_project(name="Preview", target_mode="fbd")
    before = deepcopy(service.projects.raw_project(project["id"]))
    preview = service.fbd.preview(project["id"], two_timers())
    assert "TIMER_A" in preview["svg"] and preview["gx_compile"] == "not_run"
    assert service.proposals.list(project["id"]) == []
    assert service.projects.raw_project(project["id"]) == before
    proposal = service.fbd.propose({"operation": "generate", "project_id": project["id"],
                                   "request_id": "confirm", "model": two_timers()})
    assert proposal["status"] == "accepted"
    assert len(service.projects.raw_project(project["id"])["versions"]) == 1
    candidate = service.proposal_preview(proposal["id"])
    assert candidate["svg"] == preview["svg"]
    vid = accept(service, proposal)
    assert service.projects.program(project["id"], vid) == preview["model"]
    draft = service.projects.program(project["id"], vid)
    draft["nodes"][-1]["symbol"] = "Y1"
    changed = service.fbd.preview(project["id"], draft, vid)
    assert "Y1" in changed["svg"] and changed["svg"] != preview["svg"]
    draft["nodes"][0]["x"] = -1
    with pytest.raises(FBDValidationError, match="coordinates"):
        service.fbd.preview(project["id"], draft, vid)


def test_native_report_persists_exact_source_binding_without_upgrading_compilation(service):
    project, _, proposal = generate(service)
    vid = accept(service, proposal)
    native = NativeValidationService(service)
    initial = native.list(project["id"], vid)
    assert initial["records"] == [] and initial["automatic_verification"] == "not_run"
    source = service.projects.artifact(project["id"], vid, "gxw").read_bytes()
    upload = {"filename": "saved.gxw", "data_base64": base64.b64encode(source).decode()}
    payload = command(initial["source_gxw_sha256"], native_gxw=upload)
    record = native.record(project["id"], vid, payload)
    assert native.record(project["id"], vid, payload) == record
    assert record["binding_current"] and record["native_gxw"]["matches_source_bytes"]
    assert record["native_gxw"]["selected_program_matches"] and record["native_gxw"]["integrity_verified"]
    assert record["automatic_verification"] == "not_run"
    assert native.artifact(project["id"], vid, record["id"]).read_bytes() == source
    assert service.projects.version(project["id"], vid)["validation"]["gx_compile"] == "not_run"
    assert NativeValidationService(service).list(project["id"], vid)["records"] == [record]
    with pytest.raises(ConflictError, match="request ID"):
        native.record(project["id"], vid, {**payload, "outcome": "failed"})


def test_changed_source_and_native_attachment_never_inherit_reported_pass(service):
    project, _, proposal = generate(service)
    vid = accept(service, proposal)
    native = NativeValidationService(service)
    initial = native.list(project["id"], vid)
    source = service.projects.artifact(project["id"], vid, "gxw")
    model = service.projects.program(project["id"], vid)
    model["nodes"][-1]["symbol"] = "Y1"
    changed_native = generate_object_project(model, baseline=source.read_bytes()).data
    payload = command(initial["source_gxw_sha256"], native_gxw={"filename": "changed.gxw", "data_base64": base64.b64encode(changed_native).decode()})
    record = native.record(project["id"], vid, payload)
    assert not record["native_gxw"]["matches_source_bytes"]
    assert not record["native_gxw"]["selected_program_matches"]
    attachment = native.artifact(project["id"], vid, record["id"])
    attachment.write_bytes(b"changed evidence")
    assert native.list(project["id"], vid)["records"][0]["native_gxw"]["integrity_verified"] is False
    with pytest.raises(ConflictError, match="evidence changed"):
        native.artifact(project["id"], vid, record["id"])
    source.write_bytes(source.read_bytes() + b"changed source")
    assert native.list(project["id"], vid)["records"][0]["binding_current"] is False
    with pytest.raises(ConflictError, match="GXW changed"):
        native.record(project["id"], vid, {**payload, "request_id": "retry"})


def test_report_is_scoped_to_version_and_read_only_session_cannot_record(service, tmp_path):
    project, _, proposal = generate(service)
    vid = accept(service, proposal)
    native = NativeValidationService(service)
    payload = command(native.list(project["id"], vid)["source_gxw_sha256"])
    native.record(project["id"], vid, payload)
    model = service.projects.program(project["id"], vid)
    model["nodes"][-1]["symbol"] = "Y1"
    newer = accept(service, service.fbd.propose({"operation": "edit", "project_id": project["id"],
        "version_id": vid, "request_id": "new-version", "model": model}))
    assert native.list(project["id"], newer)["records"] == []
    readonly = WorkbenchService(service.store.base_dir, tmp_path / "read-only-state", read_only=True)
    readonly_native = NativeValidationService(readonly)
    assert len(readonly_native.list(project["id"], vid)["records"]) == 1
    with pytest.raises(PermissionError):
        readonly_native.record(project["id"], vid, payload)
    assert not (tmp_path / "read-only-state").exists()


def test_copied_report_cannot_bind_to_another_version_with_identical_gxw(service):
    project, _, proposal = generate(service)
    vid = accept(service, proposal)
    native = NativeValidationService(service)
    source = service.projects.artifact(project["id"], vid, "gxw").read_bytes()
    upload = {"filename": "source.gxw", "data_base64": base64.b64encode(source).decode()}
    record = native.record(project["id"], vid, command(native.list(project["id"], vid)["source_gxw_sha256"], native_gxw=upload))
    path = service.store.version_dir(project["id"], vid) / "native-validation" / (record["id"] + ".json")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version_id"] = "another-version-with-identical-bytes"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert native.list(project["id"], vid)["records"][0]["binding_current"] is False
    with pytest.raises(ConflictError, match="different project or version"):
        native.artifact(project["id"], vid, record["id"])
    with pytest.raises(ConflictError, match="already bound"):
        native.record(project["id"], vid, command(native.list(project["id"], vid)["source_gxw_sha256"], native_gxw=upload))


def test_http_routes_require_operator_csrf_and_explicit_attestation(tmp_path):
    app = _app(tmp_path / "workspace", tmp_path / "state")
    with TestClient(app, base_url=ORIGIN) as client:
        headers = _login(client)
        project, _, proposal = generate(app.state.service)
        vid = accept(app.state.service, proposal)
        route = f'/api/projects/{project["id"]}/versions/{vid}/native-validation'
        current = client.get(route)
        assert current.status_code == 200, current.text
        payload = command(current.json()["source_gxw_sha256"])
        assert client.post(route, json=payload).status_code == 403
        assert client.post(route, json={**payload, "attested": False}, headers=headers).status_code == 422
        response = client.post(route, json=payload, headers=headers)
        assert response.status_code == 201, response.text
        assert response.json()["automatic_verification"] == "not_run"
        assert "command_hash" not in response.text
        model = app.state.service.projects.program(project["id"], vid)
        response = client.post('/api/fbd/preview', json={"project_id": project["id"], "version_id": vid, "model": model}, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["gx_compile"] == "not_run"
