"""Run an isolated, explicitly labelled browser acceptance fixture.

No user workspace, credentials, network model, GX process or PLC is touched.
The temporary workspace is removed when the local preview is stopped.
"""
import argparse
import copy
from contextlib import ExitStack, contextmanager
import json
from pathlib import Path
import sys
import tempfile
import time
import traceback
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _demo_exception_diagnostic(error):
    """Offline fixture diagnostics omit exception bodies and request values."""
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        locations = []
        for frame in traceback.extract_tb(error.__traceback__):
            path = Path(frame.filename)
            try:
                path = path.resolve().relative_to(ROOT)
            except ValueError:
                path = Path(path.name)
            locations.append(f"{path}:{frame.lineno}:{frame.name}")
        print("DEMO_JOB_EXCEPTION " + type(error).__name__ + " " + " -> ".join(locations), file=sys.stderr, flush=True)
        error = error.__cause__ or error.__context__


@contextmanager
def isolated_demo_settings(directory, provider_factory=None):
    """Keep the real settings service, replacing only its process-local I/O."""
    import config_manager
    import credential_store
    import model_provider
    from application.settings import SettingsService

    config_path = Path(directory) / "demo-config.json"
    target = credential_store.credential_target_for_profile("offline")
    config_path.write_text(json.dumps({"language": "zh-CN", "activeModelProfileId": "offline", "modelProfiles": [{
        "id": "offline", "name": "离线演示", "adapter": "openai_compatible", "model": "offline",
        "baseUrl": "https://offline.invalid/v1", "credentialTarget": target,
        "capabilities": {"tools": False}, "generationDefaults": {"temperature": 0.3}, "requestOverrides": {}}]},
        ensure_ascii=False), encoding="utf-8")
    keys = {target: "demo-key-stored-only-in-memory"}

    def read_key(target=credential_store.CREDENTIAL_TARGET):
        return keys.get(target, "")

    def write_key(value, target=credential_store.CREDENTIAL_TARGET):
        value = str(value or "").strip()
        if not value:
            raise ValueError("API Key 不能为空。")
        keys[target] = value

    def delete_key(target=credential_store.CREDENTIAL_TARGET):
        keys.pop(target, None)

    def connection_probe(profile, key):
        if key == "demo-fail":
            raise model_provider.ModelProviderError("Offline authentication failure", code="authentication")
        return "离线演示：连接测试通过（未访问外部服务）。"

    with ExitStack() as stack:
        stack.enter_context(patch.object(config_manager, "get_config_path", lambda: config_path))
        # config_manager captured these imports; isolate both references so even
        # a desktop compatibility helper cannot reach the user's Credential Manager.
        for module in (credential_store, config_manager):
            stack.enter_context(patch.object(module, "read_api_key", read_key))
            stack.enter_context(patch.object(module, "write_api_key", write_key))
        stack.enter_context(patch.object(credential_store, "delete_api_key", delete_key))
        stack.enter_context(patch.object(model_provider, "test_model_profile", connection_probe))
        if provider_factory is not None:
            stack.enter_context(patch.object(model_provider, "create_provider", provider_factory))
        yield SettingsService()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--model-delay", type=float, default=2.0, help="Offline delay in seconds for refresh/reconnect acceptance (0–10)")
    args = parser.parse_args()
    if not 0 <= args.model_delay <= 10:
        parser.error("--model-delay must be between 0 and 10 seconds")
    from application.workbench import WorkbenchService
    from integrations.web.app import create_app
    from model_provider import TextDelta
    from plc_core import PLCCore
    from plc_ir import build_plc_ir
    from session_store import SessionStore
    import uvicorn

    ladder = {"device_comments": {"X0": "启动", "X1": "停止", "X2": "保护输入", "M0": "运行保持", "Y0": "电机"}, "rungs": []}
    for i, (inputs, output) in enumerate([
        ([('NO', 'X0')], ('SET', 'M0')),
        ([('NO', 'X1')], ('RST', 'M0')),
        ([('NO', 'M0'), ('NC', 'X2')], ('COIL', 'Y0')),
    ], 1):
        ladder["rungs"].append({"rung_id": i, "header_element": None, "shared_inputs": [], "branches": [
            {"branch_id": 1, "y_offset_level": 0, "inputs": [{"type": kind, "address": address, "label": ""} for kind, address in inputs],
             "outputs": [{"type": "APP_INSTR", "opcode": output[0], "operands": [output[1]]} if output[0] in ("SET", "RST") else {"type": output[0], "address": output[1], "label": ""}]}]})

    class DemoProvider:
        def __init__(self, profile, key):
            self.profile = copy.deepcopy(profile)
            self.api_key = key

        def stream(self, request):
            time.sleep(args.model_delay)
            if request.response_contract.name == "analysis":
                output = {"summary": "演示：启动按钮置位运行保持，停止按钮复位，保护输入禁止电机输出。", "approaches": [], "missing_info": [],
                          "suggested_io": {"X": {"X0": "启动", "X1": "停止", "X2": "保护输入"}, "Y": {"Y0": "电机"}, "M": {"M0": "运行保持"}}, "assumptions": []}
            else:
                output = ladder
            yield TextDelta(json.dumps(output, ensure_ascii=False))

    with tempfile.TemporaryDirectory(prefix="gx-web-browser-qa-") as directory, \
            isolated_demo_settings(directory, DemoProvider) as settings, ExitStack() as isolated_execution:
        root = Path(directory)
        store = SessionStore(base_dir=root / "workspace")
        project = store.create_project("演示 · 电机启停控制", plc_model="FX3U")
        program = build_plc_ir(ladder, plc_model="FX3U", revision=1)
        version_id, output_dir = store.prepare_version(project["id"])
        built = PLCCore().compile_project(program, output_dir)
        store.complete_version(project["id"], version_id, {**store._ir_metadata(program), "target_mode": "ladder", "plc_model": "FX3U",
            "summary": "仅供离线页面验收的临时工程", "artifacts": built["artifacts"],
            "validation": {"status": "passed", "messages": ["离线样例的确定性结构校验通过；未运行 GX 或 PLC。"]}})
        store.create_report(project["id"], {"report_type": "program_review", "base_version_id": version_id, "status": "local_only",
            "summary": "离线样例：网络与 I/O 可读，GX 编译及仿真尚未验证。", "findings": []})
        service = WorkbenchService(store.base_dir, root / "state", settings=settings)
        original_run_job = service._run_job
        def run_job(*args, **kwargs):
            try:
                return original_run_job(*args, **kwargs)
            except Exception as error:
                _demo_exception_diagnostic(error)
                raise
        service._run_job = run_job
        # Never let browser acceptance buttons reach a real desktop execution API.
        class DemoExecution:
            def __init__(self, *_args, **_kwargs):
                pass

            def submit_read(self, *_args, **_kwargs):
                raise ValueError("Desktop execution is disabled in the isolated demo")
            submit_approved = submit_read
            def close(self, **_kwargs):
                pass
        import application.execution
        isolated_execution.enter_context(patch.object(application.execution, "GXExecutionCoordinator", DemoExecution))
        isolated_execution.enter_context(patch.object(application.execution, "read_environment", lambda: {
            "status": "unavailable", "passed": False, "desktop_execution_required": True, "gateway_started": False,
            "evidence": {"reason": "Isolated browser fixture; desktop execution disabled"}}))
        origin = f"http://127.0.0.1:{args.port}"
        app = create_app(store.base_dir, state_dir=root / "state", service=service, origin=origin,
                         operator_token="isolated-browser-acceptance", agent_token="isolated-demo-agent")
        print(f"DEMO {origin}/#token=isolated-browser-acceptance", flush=True)
        uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
