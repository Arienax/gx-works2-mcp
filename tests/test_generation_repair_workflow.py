"""Real generation/IR/SVG/CSV pipeline using deterministic model responses."""
import copy
import json
import pytest
from application.generation import GenerationRequest, GenerationDependencies, GenerationWorkflow
from application.generation_repair import GenerationValidationError, MAX_VALIDATION_REPAIRS
from application.jobs import JobCancelled
from model_provider import ModelProviderError
from test_generation_repair_assembly import ladder40, partial37, rung37


def workflow(tmp_path, initial, replies, *, previous=None, events=None, cancelled=None):
    calls = []
    def retry(*args, **kwargs):
        calls.append((args, kwargs))
        response = replies.pop(0)
        if isinstance(response, Exception): raise response
        return json.dumps(response, ensure_ascii=False)
    task = GenerationWorkflow(GenerationRequest("按已确认规格生成", previous_json=previous, model_name="offline"), tmp_path,
        lambda kind, payload: events.append((kind, payload)) if events is not None else None,
        GenerationDependencies(stream_response=lambda *a, **k: ("", json.dumps(initial, ensure_ascii=False)),
                               generate_json=retry, check_cancelled=cancelled))
    return task, calls


def test_first_generation_partial_repair_produces_complete_real_artifacts(tmp_path):
    events = []
    task, calls = workflow(tmp_path, ladder40(), [partial37()], events=events)
    result = task.run()
    assert result["validation"]["status"] == "passed" and result["repair_attempts"] == 1
    assert json.loads((tmp_path / "ladder.json").read_text(encoding="utf-8")) == ladder40(invalid=False)
    assert len(json.loads((tmp_path / "program.ir.json").read_text())["networks"]) == 40
    for artifact in result["artifacts"].values(): assert (tmp_path / artifact).stat().st_size > 0
    assert "<svg" in (tmp_path / "ladder.svg").read_text(encoding="utf-8")
    assert len(calls) == 1 and calls[0][1]["is_edit_mode"] is True
    assert calls[0][1]["current_version_json"] == ladder40()
    assert calls[0][1]["task_type"] == "repair"
    assert calls[0][1]["max_retries"] == 0 and calls[0][1]["request_timeout"] <= 120
    assert any(payload.get("stage") == "repair_merged" for _, payload in events)


def test_repair_base_is_current_generated_candidate_not_historical_version(tmp_path):
    original, attempted = ladder40(invalid=False), ladder40()
    attempted["rungs"][0]["branches"][0]["outputs"][0]["operands"][0] = "K77"
    task, calls = workflow(tmp_path, attempted, [partial37()], previous=original)
    task.run()
    result = json.loads((tmp_path / "ladder.json").read_text(encoding="utf-8"))
    assert result["rungs"][0] == attempted["rungs"][0] != original["rungs"][0]
    assert calls[0][1]["current_version_json"] == attempted
    assert original == ladder40(invalid=False)


def test_invalid_first_edit_delta_is_materialized_before_repair(tmp_path):
    original = ladder40(invalid=False)
    delta = {"mode": "partial", "device_comments": {"D30": "新的服务指针注释"}, "rungs": [ladder40()["rungs"][36]]}
    task, calls = workflow(tmp_path, delta, [partial37()], previous=original)
    task.run()
    result = json.loads((tmp_path / "ladder.json").read_text(encoding="utf-8"))
    assert len(result["rungs"]) == 40 and result["device_comments"]["D30"] == "新的服务指针注释"
    assert calls[0][1]["current_version_json"]["device_comments"]["D30"] == "新的服务指针注释"
    assert original == ladder40(invalid=False)


def test_second_repair_keeps_first_fix_and_uses_latest_diagnostic(tmp_path):
    original = ladder40()
    original["rungs"][37]["branches"][0]["outputs"][0]["opcode"] = "NOT_A_PLC_OPCODE"
    patch38 = {"mode": "partial", "rungs": [ladder40(invalid=False)["rungs"][37]], "device_comments": {}}
    task, calls = workflow(tmp_path, original, [partial37(), patch38])
    assert task.run()["repair_attempts"] == 2
    assert calls[1][1]["current_version_json"]["rungs"][36] == rung37()
    assert "NOT_A_PLC_OPCODE" in calls[1][0][0]
    assert json.loads((tmp_path / "ladder.json").read_text(encoding="utf-8")) == ladder40(invalid=False)


def test_incomplete_full_repair_does_not_erase_unrelated_rungs(tmp_path):
    task, calls = workflow(tmp_path, ladder40(), [{"rungs": [rung37()], "device_comments": {}}, partial37()])
    assert task.run()["repair_attempts"] == 2
    assert len(calls[1][1]["current_version_json"]["rungs"]) == 40


def test_invalid_candidate_never_turns_into_artifacts_by_retry_exhaustion(tmp_path):
    noop = {"mode": "partial", "rungs": []}
    task, calls = workflow(tmp_path, ladder40(), [noop] * MAX_VALIDATION_REPAIRS)
    with pytest.raises(GenerationValidationError) as rejected:
        task.run()
    assert len(calls) == MAX_VALIDATION_REPAIRS
    assert rejected.value.diagnostics["attempt_count"] == MAX_VALIDATION_REPAIRS
    assert rejected.value.diagnostics["violations"][0]["reason"] == "invalid_shared_input"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("bad", [[], {"rungs": ["bad"]}, {"rungs": [], "device_comments": {}}])
def test_shape_or_empty_candidate_recovers_with_a_full_response(tmp_path, bad):
    task, _ = workflow(tmp_path, bad, [ladder40(invalid=False)])
    assert task.run()["validation"]["status"] == "passed"


def test_model_timeout_is_not_retried_as_a_structure_error(tmp_path):
    task, calls = workflow(tmp_path, ladder40(), [ModelProviderError("secret-sentinel", code="timeout")])
    with pytest.raises(Exception) as raised: task.run()
    from application.job_errors import workflow_error_code
    assert workflow_error_code(raised.value) == "model_timeout"
    assert len(calls) == 1 and "secret-sentinel" not in str(raised.value)
    assert list(tmp_path.iterdir()) == []


def test_cancellation_is_not_wrapped_into_failure_or_retried(tmp_path):
    def cancelled(): raise JobCancelled()
    task, calls = workflow(tmp_path, ladder40(), [partial37()], cancelled=cancelled)
    with pytest.raises(JobCancelled): task.run()
    assert not calls and list(tmp_path.iterdir()) == []
