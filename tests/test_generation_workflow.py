import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import api
from application.generation import (
    GenerationDependencies, GenerationError, GenerationRequest, GenerationWorkflow,
)
from i18n import set_language
from model_provider import ModelProviderError, TextDelta


def _ladder():
    return {
        "device_comments": {"X0": "Input", "Y0": "Output"},
        "rungs": [{"rung_id": 1, "header_element": None, "shared_inputs": [],
                   "branches": [{"branch_id": 1, "y_offset_level": 0,
                                 "inputs": [{"type": "NO", "address": "X0", "label": "Input"}],
                                 "outputs": [{"type": "COIL", "address": "Y0", "label": "Output"}]}]}],
    }


def test_generation_runs_with_all_gui_imports_blocked(tmp_path):
    script = '''
import importlib.abc, json, sys
class BlockGUI(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "main" or fullname == "qt_compat" or fullname.startswith(("PyQt", "PySide")):
            raise AssertionError("GUI import: " + fullname)
sys.meta_path.insert(0, BlockGUI())
from application.generation import GenerationWorkflow, GenerationRequest, GenerationDependencies
from application.review import InspectionWorkflow
from application.planning import EvidenceDebugPlanWorkflow, SimulatorTestPlanWorkflow
result = GenerationWorkflow(
    GenerationRequest("X0 controls Y0", target_mode="st", model_name="offline"), sys.argv[1],
    dependencies=GenerationDependencies(stream_response=lambda *a, **k: ("", json.dumps({"st_code":"Y0 := X0;"}))),
).run()
assert result["artifacts"] == {"st": "program.st"}
assert "main" not in sys.modules and "qt_compat" not in sys.modules
'''
    env = dict(os.environ, PYTHONPATH=str(Path("src").resolve()))
    completed = subprocess.run([sys.executable, "-c", script, str(tmp_path)],
                               env=env, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert (tmp_path / "program.st").read_text(encoding="utf-8") == "Y0 := X0;"


def test_generation_trusts_confirmed_spec_without_posthoc_approach_rejection(tmp_path):
    ladder = _ladder()
    spec = {"selected_approach": {"name": "MOV approach", "generation_contract": {
        "required_opcodes": ["MOV"], "enforce": True}}}
    request = GenerationRequest("X0 controls Y0", confirmed_context=spec, model_name="offline")
    workflow = GenerationWorkflow(request, tmp_path, dependencies=GenerationDependencies(
        stream_response=lambda *a, **k: ("", json.dumps(ladder)),
        generate_json=lambda *a, **k: pytest.fail("Generation must not enter a semantic repair loop"),
    ))
    spec.clear()
    request.confirmed_context.clear()
    result = workflow.run()
    assert result["validation"]["status"] == "candidate_ready"
    assert result["validation_profile"] == "generation_structural"
    assert result["repair_attempts"] == 0
    assert result["contract_mismatch"] is None
    assert json.loads((tmp_path / "ladder.json").read_text(encoding="utf-8")) == ladder
    assert (tmp_path / result["artifacts"]["program_csv"]).is_file()


@pytest.mark.parametrize("mutation", ["delete", "rung", "device", "comment", "full"])
def test_contract_repair_rejects_scope_escape_without_hidden_retry(tmp_path, mutation):
    ladder = _ladder()
    partial = {"mode": "partial", "rungs": [], "delete_rung_ids": [], "device_comments": {}}
    if mutation == "delete":
        partial["delete_rung_ids"] = [1]
    elif mutation == "rung":
        partial["rungs"] = [{"rung_id": 2}]
    elif mutation == "device":
        partial["rungs"] = ladder["rungs"]
        partial["rungs"][0]["branches"][0]["inputs"][0]["address"] = "X1"
    elif mutation == "comment":
        partial["device_comments"] = {"D100": "Unrelated device"}
    else:
        partial = ladder
    workflow = GenerationWorkflow(
        GenerationRequest("Repair current approach", previous_json=_ladder(),
                          task_type="contract_repair", repair_mode=True,
                          allowed_rung_ids=[1], allowed_addresses=["X0", "Y0"], model_name="offline"),
        tmp_path, dependencies=GenerationDependencies(
            stream_response=lambda *a, **k: ("", json.dumps(partial)),
            generate_json=lambda *a, **k: pytest.fail("Contract repair secretly retried"),
        ),
    )
    with pytest.raises(GenerationError, match="不会继续隐藏重试"):
        workflow.run()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("target_mode", ["ladder", "st"])
def test_rejected_response_cannot_fallback_or_create_artifacts(monkeypatch, tmp_path, target_mode):
    monkeypatch.setattr(api, "_build_knowledge_context", lambda *a, **k: "")
    events = []
    calls = []
    candidate = _ladder() if target_mode == "ladder" else {"st_code": "(* 正在检查输入并准备输出。 *)\nY0 := X0;"}
    if target_mode == "ladder":
        candidate["device_comments"]["Y0"] = "正在检查输入并准备输出。"
    class Provider:
        def stream(self, request):
            calls.append(request)
            yield TextDelta(json.dumps(candidate, ensure_ascii=False))
    workflow = GenerationWorkflow(
        GenerationRequest("X0 controls Y0", target_mode=target_mode, model_name="offline", response_language="en"),
        tmp_path, lambda kind, payload: events.append((kind, payload)),
        GenerationDependencies(provider=Provider(),
                               generate_json=lambda *a, **k: pytest.fail("Rejected response retried")),
    )
    with pytest.raises(GenerationError):
        workflow.run()
    assert len(calls) == 1
    assert list(tmp_path.iterdir()) == []
    assert {kind for kind, payload in events} == {"progress"}


def test_provider_and_language_remain_bound_across_transport_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "_build_knowledge_context", lambda *a, **k: "")
    calls = []
    accepted = json.dumps({"st_code": "(* The input controls the output. *)\nY0 := X0;"})
    class Provider:
        def stream(self, request):
            calls.append(request)
            if request.stream:
                yield TextDelta("Unaccepted partial output")
                set_language("ja")
                monkeypatch.setattr(api, "get_active_provider", lambda: pytest.fail("Provider drift"))
                raise ModelProviderError("Offline transport failure")
            yield TextDelta(accepted)
    provider = Provider()
    monkeypatch.setattr(api, "get_active_provider", lambda: provider)
    set_language("en")
    request = GenerationRequest("X0 controls Y0", target_mode="st", model_name="offline")
    set_language("zh-CN")
    events = []
    result = GenerationWorkflow(request, tmp_path, lambda *event: events.append(event)).run()
    assert result["validation"]["status"] == "candidate_ready"
    assert [(call.stream, call.response_language) for call in calls] == [(True, "en"), (False, "en")]
    assert not any("Unaccepted partial" in str(payload) for _, payload in events)


def test_provider_scope_is_nested_and_restored(monkeypatch):
    first, second, default = object(), object(), object()
    monkeypatch.setattr(api, "get_active_provider", lambda: default)
    with api.provider_scope(first):
        assert api._workflow_provider() is first
        with api.provider_scope():
            assert api._workflow_provider() is first
        with api.provider_scope(second):
            assert api._workflow_provider() is second
        assert api._workflow_provider() is first
    assert api._workflow_provider() is default
