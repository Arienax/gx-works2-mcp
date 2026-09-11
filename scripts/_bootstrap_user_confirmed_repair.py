from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path, old, new, label):
    path = ROOT / path
    text = path.read_text(encoding="utf-8")
    if new in text:
        print("already applied:", label)
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
    print("applied:", label)


replace_once(
    "src/application/generation.py",
    '''            model_user_input = self.user_input\n            if is_edit_mode and not self.repair_mode:\n                # This is a model instruction, not an application-side gate.\n                # The parser deliberately continues to accept both partial and\n                # full JSON so an imperfect model choice never becomes another\n                # hard-validation failure or hidden retry loop.\n                model_user_input = (\n                    '这是对系统提供的 Current version JSON 的修改请求。除非用户明确要求整体重写，'\n                    '优先返回 mode="partial"：device_comments 只列新增或修改项，rungs 只列修改或新增的完整梯级，'\n                    'delete_rung_ids 只列需要删除的梯级；不要重复输出未修改梯级。'\n                    '如果你仍返回完整 JSON，应用也会正常接受，不需要为了格式选择重新生成。\\n\\n'\n                    '用户修改要求：\\n'\n                    + self.user_input\n                )\n''',
    '''            model_user_input = self.user_input\n            if self.target_mode == "ladder" and not self.repair_mode:\n                output_discipline = (\n                    '输出协议纪律：只返回协议允许的 JSON 字段，不要输出解释性正文。'\n                    'debug_note 是可选字段，默认省略；不要用 debug_note 记录推理、修改原因或长说明。'\n                    '已有 device_comments 无必要不要改写。label、debug_note、device_comment 单条文本目标不超过48字符，'\n                    '硬上限64字符；返回前自行检查字段名和文本长度。\\n\\n'\n                )\n                if is_edit_mode:\n                    # This is a model instruction, not an application-side gate.\n                    # The parser deliberately continues to accept both partial and\n                    # full JSON so an imperfect model choice never becomes another\n                    # hard-validation failure or hidden retry loop.\n                    model_user_input = (\n                        output_discipline\n                        + '这是对系统提供的 Current version JSON 的修改请求。除非用户明确要求整体重写，'\n                        '优先返回 mode="partial"：device_comments 只列确实需要修改的注释，rungs 只列修改或新增的完整梯级，'\n                        'delete_rung_ids 只列需要删除的梯级；不要重复输出未修改梯级。'\n                        '如果你仍返回完整 JSON，应用也会正常接受，不需要为了格式选择重新生成。\\n\\n'\n                        '用户修改要求：\\n'\n                        + self.user_input\n                    )\n                else:\n                    model_user_input = output_discipline + '用户要求：\\n' + self.user_input\n''',
    "tighten direct generation output discipline",
)

replace_once(
    "src/application/generation.py",
    '''            validation_errors = (PLCJsonValidationError, PLCIRValidationError, json.JSONDecodeError)\n            try:\n                parsed_json = parse_candidate(json_str)\n            except validation_errors as error:\n                # No hidden semantic re-generation loop. The diagnostics layer\n                # records the exact parse/shape failure for the operator.\n                raise GenerationValidationError(\n                    [error], attempts=0, language=self.response_language,\n                    stop_reason="final_validation",\n                ) from error\n''',
    '''            def persist_repair_candidate():\n                # Private staging only: never expose an invalid candidate as a project artifact.\n                if self.target_mode != "ladder" or not isinstance(json_str, str):\n                    return\n                if not json_str.strip() or len(json_str) > 512000:\n                    return\n                (self.output_dir / "repair_candidate.json").write_text(json_str, encoding="utf-8")\n\n            validation_errors = (PLCJsonValidationError, PLCIRValidationError, json.JSONDecodeError)\n            try:\n                parsed_json = parse_candidate(json_str)\n            except validation_errors as error:\n                # No hidden semantic re-generation loop. Preserve the rejected\n                # candidate privately so an operator can explicitly request one repair.\n                persist_repair_candidate()\n                raise GenerationValidationError(\n                    [error], attempts=0, max_attempts=0, language=self.response_language,\n                    stop_reason="final_validation",\n                ) from error\n''',
    "persist rejected candidate for explicit repair",
)

replace_once(
    "src/application/generation.py",
    '''        except (PLCJsonValidationError, PLCIRValidationError) as error:\n            raise GenerationValidationError(\n                [error], attempts=0, language=self.response_language,\n                stop_reason="final_validation",\n            ) from error\n''',
    '''        except (PLCJsonValidationError, PLCIRValidationError) as error:\n            try:\n                persist_repair_candidate()\n            except (NameError, OSError):\n                pass\n            raise GenerationValidationError(\n                [error], attempts=0, max_attempts=0, language=self.response_language,\n                stop_reason="final_validation",\n            ) from error\n''',
    "mark direct structural failure as zero automatic repairs",
)

replace_once(
    "src/application/generation_repair.py",
    '''REPAIR_REASONS = frozenset({"invalid_shared_input", "invalid_ladder_structure", "repair_base_invalid",\n    "repair_identity_invalid", "repair_shape_invalid", "repair_scope_violation", "repair_no_progress"})\n''',
    '''REPAIR_REASONS = frozenset({"invalid_shared_input", "invalid_ladder_structure", "field_too_long",\n    "repair_base_invalid", "repair_identity_invalid", "repair_shape_invalid", "repair_scope_violation",\n    "repair_no_progress"})\n''',
    "add field_too_long diagnostic",
)

replace_once(
    "src/application/generation_repair.py",
    '''    reason = (error.reason if isinstance(error, RepairAssemblyError) else\n              "invalid_json_object" if isinstance(error, json.JSONDecodeError) else\n              "invalid_shared_input" if "shared_inputs" in safe and "parallel_block" in text else\n              "invalid_ladder_structure")\n''',
    '''    reason = (error.reason if isinstance(error, RepairAssemblyError) else\n              "invalid_json_object" if isinstance(error, json.JSONDecodeError) else\n              "invalid_shared_input" if "shared_inputs" in safe and "parallel_block" in text else\n              "field_too_long" if ("must be <=" in text or "invalid text length" in text) else\n              "invalid_ladder_structure")\n''',
    "classify oversized text fields",
)

replace_once(
    "src/application/generation_repair.py",
    '''class GenerationValidationError(GenerationError):\n    def __init__(self, errors, *, attempts, language, stop_reason="attempt_limit"):\n        rows = [validation_diagnostic(error) for error in errors][-16:]\n        self.diagnostics = {"response_language": language, "contract_name": "ladder",\n            "diagnostic_id": hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()[:16],\n            "violations": rows, "violation_count": len(rows), "truncated": False,\n            "stage": "generation_validation", "attempt_count": attempts,\n            "max_attempts": MAX_VALIDATION_REPAIRS, "stop_reason": stop_reason}\n''',
    '''class GenerationValidationError(GenerationError):\n    def __init__(self, errors, *, attempts, language, stop_reason="attempt_limit",\n                 max_attempts=MAX_VALIDATION_REPAIRS):\n        rows = [validation_diagnostic(error) for error in errors][-16:]\n        self.diagnostics = {"response_language": language, "contract_name": "ladder",\n            "diagnostic_id": hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()[:16],\n            "violations": rows, "violation_count": len(rows), "truncated": False,\n            "stage": "generation_validation", "attempt_count": attempts,\n            "max_attempts": max_attempts, "stop_reason": stop_reason}\n''',
    "allow zero automatic repair budget in diagnostics",
)

replace_once(
    "src/plc_generation_contract.py",
    '''            "Labels, debug notes and device comments must be at most 64 characters.",\n''',
    '''            "debug_note is optional: omit it by default and never use it for reasoning or long explanations.",\n            "Keep labels, debug notes and device comments concise: target <=48 characters, hard limit 64.",\n''',
    "strengthen model-facing annotation discipline",
)

replace_once(
    "src/application/workbench.py",
    '''    def submit(self, command):\n''',
    '''    def repair_generation(self, job_id, request_id):\n        """Submit one operator-confirmed model call to repair a rejected ladder shape."""\n        self.writable()\n        record_id(request_id, "request")\n        with self.lock.thread_lock:\n            if not self.jobs:\n                raise KeyError(job_id)\n            record = self.jobs._load(record_id(job_id, "job"))\n            if (record.get("kind") != "generation" or record.get("status") != "failed"\n                    or record.get("error_code") != "generation_validation_failed"):\n                raise ConflictError("Only a failed structural generation can be repaired")\n            snapshot = copy.deepcopy(record.get("snapshot") or {})\n            self._check_snapshot(snapshot)\n            project_id = snapshot["project_id"]\n            version_id = snapshot.get("version_id")\n            root = contained(self.state_dir / "staging" / record_id(job_id), self.state_dir / "staging")\n            candidate_path = contained(root / "repair_candidate.json", root)\n            if not candidate_path.is_file():\n                raise ConflictError("The rejected candidate is no longer available for repair")\n            candidate = candidate_path.read_text(encoding="utf-8")\n            if not candidate.strip() or len(candidate) > 512000:\n                raise ConflictError("The rejected candidate is too large or empty")\n            details = record.get("error_details") or {}\n            violations = details.get("violations") if isinstance(details, dict) else []\n            locations = []\n            for item in violations or []:\n                if isinstance(item, dict):\n                    path = item.get("path")\n                    reason = item.get("reason")\n                    if isinstance(path, str):\n                        locations.append(path + (f" ({reason})" if isinstance(reason, str) else ""))\n            language = snapshot.get("response_language") if snapshot.get("response_language") in ("zh-CN", "en", "ja") else "zh-CN"\n\n        repair_text = (\n            "这是用户明确确认的一次结构修复。不要重新分析需求，也不要改变控制逻辑、地址、参数、触点极性或未出错梯级。"\n            "只修复下面失败候选的 JSON 协议/结构问题。debug_note 是可选字段，默认删除；不要用它解释推理。"\n            "label、debug_note、device_comment 单条目标不超过48字符且绝不能超过64字符。"\n            "只使用梯形图 schema 允许的字段，保持原候选的 mode 和语义，修好后只返回 JSON。\\n"\n            "失败位置：" + ("；".join(locations) if locations else "ladder schema") + "\\n\\n"\n            "失败候选 JSON：\\n" + candidate\n        )\n        return self.submit({\n            "kind": "generation",\n            "project_id": project_id,\n            "version_id": version_id,\n            "request_id": request_id,\n            "text": repair_text,\n            "response_language": language,\n            "attachment_ids": [],\n        })\n\n    def submit(self, command):\n''',
    "add explicit user-confirmed repair command",
)

replace_once(
    "src/integrations/web/schemas.py",
    '''class ProposalDecision(Command):\n''',
    '''class GenerationRepair(Command):\n    request_id: str = Field(min_length=1, max_length=128)\n\n\nclass ProposalDecision(Command):\n''',
    "add generation repair request schema",
)

replace_once(
    "src/integrations/web/app.py",
    '''                      JobCreate, ProposalDecision, ExecutionProposal, AgentCall,\n''',
    '''                      JobCreate, GenerationRepair, ProposalDecision, ExecutionProposal, AgentCall,\n''',
    "import generation repair schema",
)

replace_once(
    "src/integrations/web/app.py",
    '''    @app.get("/api/jobs/{job_id}/diagnostics")\n''',
    '''    @app.post("/api/jobs/{job_id}/repair", status_code=202, response_model=dto.Job, response_model_exclude_unset=True)\n    def repair_generation(job_id: str, command: GenerationRepair):\n        return service.repair_generation(job_id, command.request_id)\n\n    @app.get("/api/jobs/{job_id}/diagnostics")\n''',
    "add user-confirmed repair endpoint",
)

job_failure = ROOT / "web/src/features/JobFailure.tsx"
job_failure.write_text('''import type { Job } from "../api/client";\nimport { Button } from "../components/ui";\n\nconst reasons: Record<string, string> = {\n  latin_prose: "回复含有不符合所选语言的英文说明",\n  japanese_script: "回复含有不符合所选语言的日文",\n  non_english_script: "回复含有不符合所选语言的文字",\n  unsupported_script: "回复含有不支持的语言文字",\n  ambiguous_han_only: "无法确认回复是否为所选语言",\n  invalid_json_object: "回复格式不完整或不是有效数据",\n  invalid_prose_field: "说明字段格式错误",\n  invalid_code_field: "程序字段格式错误",\n  invalid_shared_input: "公共串联输入中不能包含并联块；请在分支输入中表达并联逻辑。",\n  invalid_ladder_structure: "梯形图结构或指令编码不符合协议。",\n  field_too_long: "文本字段超过协议长度限制；请缩短或省略该说明。",\n  repair_base_invalid: "缺少可合并的完整候选，修复必须返回完整程序。",\n  repair_identity_invalid: "梯级编号重复或无效，无法安全合并修复。",\n  repair_shape_invalid: "修复响应的 JSON 结构不符合协议。",\n  repair_scope_violation: "修复试图删除、新增或重排梯级，已阻止。",\n  repair_no_progress: "修复未改变失败候选。",\n};\n\nconst errorMessages: Record<string, string> = {\n  model_timeout: "模型服务请求超时，请稍后重试。",\n  model_authentication: "模型服务认证失败，请检查 API Key 和访问权限。",\n  model_rate_limit: "模型服务请求过于频繁，请稍后重试。",\n  model_invalid_request: "模型服务拒绝了请求，请检查模型配置和输入。",\n  model_unavailable: "模型服务暂时不可用，请检查连接或稍后重试。",\n  model_protocol: "模型未返回有效候选结果，请重试或更换模型。",\n  model_provider_error: "模型服务调用失败，请检查配置或稍后重试。",\n  generation_failed: "生成流程失败，确认规格和已有版本未被修改。",\n};\n\nfunction FailureMessage({ job, t }: { job: Job; t: (key: string) => string }) {\n  if (!job.error_code) return null;\n  if (job.error_code === "generation_validation_failed") return <div className="job-failure" role="alert">\n    <p className="error-text">{t("梯形图候选结构不符合协议，未接受任何程序。")}</p>\n    {job.error_details?.violations?.map((violation, i) => <p key={i}>\n      <code>{violation.path}</code><br /><span>{t(reasons[violation.reason] || "回复内容不符合要求")}</span>\n    </p>)}\n    <p className="muted">{t("系统没有自动再次调用模型。可由你确认后仅修复当前候选的结构问题。")}</p>\n  </div>;\n  if (job.error_code !== "response_rejected") return <p className="error-text">{t(errorMessages[job.error_code] || job.error_code)}</p>;\n  return <div className="job-failure" role="alert">\n    <p className="error-text">{t("模型回复未通过检查，请重试。")}</p>\n    {job.error_details?.violations?.length ? <ul>\n      {job.error_details.violations.map((violation, i) => <li key={i}>\n        {t(violation.path.startsWith("reasoning") ? "思考内容" : violation.path.startsWith("tool_calls") ? "工具参数" : "回复内容")}：{t(reasons[violation.reason] || "回复内容不符合要求")}\n      </li>)}\n    </ul> : <p className="muted">{t("此历史任务未记录具体原因；新任务将显示检查详情。")}</p>}\n  </div>;\n}\n\nexport function JobFailure({ job, busy, onRepair, t }: {\n  job: Job;\n  busy?: boolean;\n  onRepair?: () => void;\n  t: (key: string) => string;\n}) {\n  if (!job.error_code) return null;\n  const repairable = job.kind === "generation" && job.error_code === "generation_validation_failed" && !!onRepair;\n  return <section>\n    <FailureMessage job={job} t={t} />\n    {repairable && <Button disabled={busy} onClick={onRepair}>{t("让 AI 修复")}</Button>}\n    <div className="job-diagnostic-export">\n      <a className="button secondary" href={`/api/jobs/${encodeURIComponent(job.id)}/diagnostics`} download>\n        {t("下载错误诊断日志")}\n      </a>\n      <p className="muted">{t("任务编号")}：<code>{job.id}</code></p>\n      <p className="muted">{t("仅导出诊断元数据，不含 API Key、提示词、回复正文或工程文件；不会自动上传。")}</p>\n    </div>\n  </section>;\n}\n''', encoding="utf-8", newline="\n")
print("replaced JobFailure.tsx")

replace_once(
    "web/src/App.tsx",
    '''  async function saveSpec(value: Spec) {\n''',
    '''  async function repairFailedGeneration(job: Job) {\n    if (job.kind !== "generation" || job.error_code !== "generation_validation_failed") return;\n    if (!window.confirm(t("将调用模型一次，仅修复当前候选的结构/协议错误，不重新分析需求。继续吗？"))) return;\n    const repaired = await api<Job>(`/jobs/${encodeURIComponent(job.id)}/repair`, "POST", { request_id: key() });\n    if (activeProjectRef.current !== pid) return;\n    setEvents([]);\n    setJobId(repaired.id);\n    setJobs((old) => [repaired, ...old.filter((item) => item.id !== repaired.id)]);\n    setPanel("agent");\n  }\n\n  async function saveSpec(value: Spec) {\n''',
    "add frontend repair action",
)

replace_once(
    "web/src/App.tsx",
    '''                  <JobFailure job={currentJob} t={t} />\n''',
    '''                  <JobFailure job={currentJob} busy={!canWrite}\n                    onRepair={() => void guarded(() => repairFailedGeneration(currentJob))} t={t} />\n''',
    "wire repair button",
)

# Long-term CI follows the new main branch and PRs instead of the retired refactor branch.
replace_once(
    ".github/workflows/generation-fast-path.yml",
    '''on:\n  push:\n    branches: [refactor/generation-fast-path]\n  workflow_dispatch:\n''',
    '''on:\n  push:\n    branches: [main]\n  pull_request:\n    branches: [main]\n  workflow_dispatch:\n''',
    "retarget fast-path CI to main",
)

replace_once(
    ".github/workflows/generation-fast-path.yml",
    '''            tests/test_generation_repair_workflow.py `\n            tests/test_generation_delivery.py `\n''',
    '''            tests/test_generation_repair_workflow.py `\n            tests/test_user_confirmed_generation_repair.py `\n            tests/test_generation_delivery.py `\n''',
    "add explicit repair regression to CI",
)

(ROOT / "tests/test_user_confirmed_generation_repair.py").write_text(r'''import json

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
''', encoding="utf-8", newline="\n")
print("created repair regression tests")
