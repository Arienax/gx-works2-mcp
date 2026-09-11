from __future__ import annotations

import runpy
import sys
from pathlib import Path

module = runpy.run_path("scripts/_bootstrap_gx_send_delete_v2.py", run_name="bootstrap_gx_send_delete_v2")
# v2 executes at module load and either succeeds or raises.

regression = Path("tests/test_gx_execution_ui_and_project_delete.py")
text = regression.read_text(encoding="utf-8")
old = '''def test_execution_failure_is_not_presented_as_completed():
    assert 'currentJob.kind === "execution"' in APP
    assert '["failed", "interrupted", "conflict"].includes(String(currentJob.result?.status || ""))' in APP
'''
new = '''def test_execution_failure_is_not_presented_as_completed():
    assert 'currentJob?.kind === "execution"' in APP
    assert '["failed", "interrupted", "conflict"].includes(String(currentJob.result?.status || ""))' in APP
'''
if new not in text:
    if text.count(old) != 1:
        raise RuntimeError("generated regression test preimage mismatch")
    regression.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
    print("[ok]   regression: optional-chain execution status assertion")

web_test = Path("tests/test_web_api.py")
text = web_test.read_text(encoding="utf-8")
old = '''def test_candidate_and_execution_preview_theme_preserves_ir_diff_and_proposal_hash(tmp_path):
    workspace = tmp_path / "workspace"
'''
new = '''def test_candidate_and_execution_preview_theme_preserves_ir_diff_and_proposal_hash(tmp_path, monkeypatch):
    import application.execution
    monkeypatch.setattr(application.execution, "read_gx_environment", lambda: {
        "status": "ready", "passed": True, "desktop_execution_required": True,
        "gx_works2_running": True, "project_open": True, "message": "GX Works2 已运行。",
    })
    workspace = tmp_path / "workspace"
'''
if new not in text:
    if text.count(old) != 1:
        raise RuntimeError("preview test preimage mismatch")
    text = text.replace(old, new, 1)
    print("[ok]   web test: mock GX readiness for proposal preview")

old = '''    service = WorkbenchService(workspace, tmp_path / "state")
    attempts, release, held = threading.Event(), threading.Event(), threading.Event()
'''
new = '''    service = WorkbenchService(workspace, tmp_path / "state")
    import application.execution
    monkeypatch.setattr(application.execution, "read_gx_environment", lambda: {
        "status": "ready", "passed": True, "desktop_execution_required": True,
        "gx_works2_running": True, "project_open": True, "message": "GX Works2 已运行。",
    })
    attempts, release, held = threading.Event(), threading.Event(), threading.Event()
'''
# This anchor occurs only in the cancellation test in the reviewed branch.
if new not in text:
    if text.count(old) != 1:
        raise RuntimeError(f"cancel test preimage mismatch: {text.count(old)}")
    text = text.replace(old, new, 1)
    print("[ok]   web test: mock GX readiness for cancellation ownership test")

web_test.write_text(text, encoding="utf-8", newline="\n")
