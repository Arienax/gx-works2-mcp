import json

from fastapi.testclient import TestClient

from application.generation import GenerationDependencies, GenerationRequest, GenerationWorkflow
from application.workbench import WorkbenchService
from model_provider import TextDelta
from test_web_api import ORIGIN, _app, _ladder, _login, offline


class RepairProvider:
    def __init__(self):
        self.requests = []

    def stream(self, request):
        self.requests.append(request)
        payload = _ladder()
        if len(self.requests) == 1:
            payload["rungs"][0]["debug_note"] = "过长说明" * 20
        raw = json.dumps(payload, ensure_ascii=False)
        yield TextDelta(raw)


def test_incremental_prompt_prefers_minimal_annotations(tmp_path):
    observed = {}

    def stream(user_input, *args, **kwargs):
        observed["input"] = user_input
        return "", json.dumps(_ladder(), ensure_ascii=False)

    GenerationWorkflow(
        GenerationRequest(
            "把X0改为上升沿",
            previous_json=_ladder(),
            model_name="offline",
        ),
        tmp_path,
        dependencies=GenerationDependencies(stream_response=stream),
    ).run()
    prompt = observed["input"]
    assert "debug_note 是可选字段，默认省略" in prompt
    assert "不要用 debug_note 记录推理" in prompt
    assert "目标不超过48字符" in prompt
    assert "已有 device_comments 无必要不要改写" in prompt
    assert '优先返回 mode="partial"' in prompt


def test_structural_failure_waits_for_user_then_repairs_once(offline, tmp_path):
    provider = RepairProvider()
    service = WorkbenchService(
        tmp_path / "workspace", tmp_path / "state",
        model_factory=lambda: (provider, {"model": "offline"}),
    )
    with TestClient(_app(service.store.base_dir, service.state_dir, service=service), base_url=ORIGIN) as client:
        headers = _login(client)
        project = client.post("/api/projects", json={"name": "repair"}, headers=headers).json()["id"]
        service.store.set_confirmed_spec(project, {"summary": "X0 controls Y0", "io_table": [], "parameters": []})
        created = client.post("/api/jobs", headers=headers, json={
            "project_id": project,
            "kind": "generation",
            "request_id": "bad-generation",
            "text": "X0 controls Y0",
            "response_language": "zh-CN",
        })
        assert created.status_code == 202, created.text
        bad_job = created.json()["id"]
        service.jobs._futures[bad_job].result(timeout=15)
        failed = client.get(f"/api/jobs/{bad_job}").json()
        assert failed["status"] == "failed"
        assert failed["error_code"] == "generation_validation_failed"
        assert failed["error_details"]["attempt_count"] == 0
        assert failed["error_details"]["max_attempts"] == 0
        assert failed["error_details"]["violations"][0]["reason"] == "field_too_long"
        assert len(provider.requests) == 1, "structural failure must not auto-call the model again"
        assert service.projects.project(project)["version_count"] == 0
        candidate = service.state_dir / "staging" / bad_job / "repair_candidate.json"
        assert candidate.is_file()

        repaired = client.post(f"/api/jobs/{bad_job}/repair", headers=headers, json={"request_id": "repair-once"})
        assert repaired.status_code == 202, repaired.text
        repair_job = repaired.json()["id"]
        service.jobs._futures[repair_job].result(timeout=15)
        completed = client.get(f"/api/jobs/{repair_job}").json()
        assert completed["status"] == "completed", completed
        assert len(provider.requests) == 2
        second_prompt = str(provider.requests[1].messages[-1].content)
        assert "用户明确确认的一次结构修复" in second_prompt
        assert "只修复" in second_prompt
        assert "debug_note" in second_prompt
        assert service.projects.project(project)["version_count"] == 1


def test_failure_ui_offers_explicit_repair_not_fake_automatic_attempts():
    text = open("web/src/features/JobFailure.tsx", encoding="utf-8").read()
    assert "让 AI 修复" in text
    assert "系统没有自动再次调用模型" in text
    assert "已执行结构修复" not in text
