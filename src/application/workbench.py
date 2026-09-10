"""Application commands shared by the HTTP operator and connected MCP agents."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import tempfile
import uuid
from pathlib import Path

from application.projects import ProjectService, contained, public, record_id
from application.settings import SettingsService
from application.workspace import WorkspaceWriterLock, ConflictError, atomic_json, canonical_hash, read_json
from tool_messages import ToolCall
from tool_runtime import public_tool_result_data


class WorkbenchService:
    def __init__(self, workspace, state_dir, *, read_only=False, settings=None, model_factory=None):
        self.projects = ProjectService(workspace)
        self.store = self.projects.store
        self.state_dir = Path(state_dir).resolve()
        self.read_only = read_only
        self.settings = settings or SettingsService()
        self.model_factory = model_factory or self.settings.model_snapshot
        self.lock = None
        self.jobs = None
        self.proposals = None
        self.execution = None
        from application.fbd import FBDService
        self.fbd = FBDService(self)

    def start(self):
        if not self.read_only:
            from application.jobs import JobManager
            from application.proposals import ProposalService
            from application.execution import GXExecutionCoordinator
            self.lock = WorkspaceWriterLock(self.store.base_dir).acquire()
            try:
                self.jobs = JobManager(self.state_dir, self.lock)
                self.proposals = ProposalService(self.store, self.state_dir, self.lock)
                self.execution = GXExecutionCoordinator(self.store)
            except Exception:
                self.close()
                raise

    def close(self):
        # Keep ownership until outstanding workers reach completion/checkpoints.
        if self.jobs:
            self.jobs.shutdown(wait=True)
        if self.execution:
            self.execution.close(wait=True)
        if self.lock:
            self.lock.release()

    def writable(self):
        if self.read_only or not self.lock:
            raise PermissionError("工作台以只读模式打开。")
        self.lock.require_acquired()

    def create_project(self, **values):
        self.writable()
        with self.lock.thread_lock:
            project = self.store.create_project(**values)
            return self.projects.project(project["id"])

    def update_project(self, project_id, **values):
        self.writable()
        with self.lock.thread_lock:
            self.projects.raw_project(project_id)
            self.store.update_project_settings(project_id, **values)
            return self.projects.project(project_id)

    def activate_version(self, project_id, version_id, expected_active_version_id):
        self.writable()
        with self.lock.thread_lock:
            project = self.projects.raw_project(project_id)
            self.projects.raw_version(project_id, version_id)
            if project.get("active_version_id") != expected_active_version_id:
                raise ConflictError("当前版本已被其他窗口改变，请刷新。")
            self.store.activate_version(project_id, version_id)
            return self.projects.project(project_id)

    def set_spec(self, project_id, spec, expected_hash):
        from confirmed_spec import canonicalize_confirmed_spec, validate_spec_draft
        from plc_ir import canonical_sha256
        self.writable()
        with self.lock.thread_lock:
            project = self.projects.raw_project(project_id)
            current = project.get("confirmed_spec")
            if (canonical_sha256(current) if current is not None else None) != expected_hash:
                raise ConflictError("确认规格已变化，请重新加载。")
            issues = validate_spec_draft(spec, project.get("plc_model"))
            if issues.get("errors"):
                return {"valid": False, "issues": public(issues)}
            normalized = canonicalize_confirmed_spec(spec)
            issues = validate_spec_draft(normalized, project.get("plc_model"))
            if issues.get("errors"):
                return {"valid": False, "issues": public(issues)}
            self.store.set_confirmed_spec(project_id, normalized)
            persisted = self.projects.raw_project(project_id)["confirmed_spec"]
            return {"valid": True, "spec": public(persisted), "hash": canonical_sha256(persisted)}

    def upload_attachment(self, project_id, filename, data_base64):
        from session_store import detect_image_media_type
        self.writable()
        self.projects.raw_project(project_id)
        data = base64.b64decode(data_base64, validate=True)
        if not data or len(data) > 30 * 1024 * 1024 or not detect_image_media_type(data):
            raise ValueError("请添加总计不超过 30 MiB 的 JPEG、PNG、GIF 或 WebP 图片。")
        with self.lock.thread_lock:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=self.state_dir, prefix="upload-") as directory:
                path = Path(directory) / (Path(filename.replace("\\", "/")).name or "image")
                path.write_bytes(data)
                record = self.store.import_image_attachments(project_id, [path])[0]
            atomic_json(self.state_dir / "attachments" / (record["attachment_id"] + ".json"),
                        {"project_id": project_id, "record": record})
            return {key: record[key] for key in ("attachment_id", "filename", "media_type", "size_bytes")}

    def _attachments(self, project_id, ids):
        from model_provider import ImageAttachment
        attachments = []
        for attachment_id in ids:
            path = contained(self.state_dir / "attachments" / (record_id(attachment_id) + ".json"), self.state_dir)
            saved = read_json(path)
            if saved["project_id"] != project_id:
                raise ValueError("Attachment belongs to another project")
            record = saved["record"]
            data = self.store.load_image_attachment(project_id, record)
            attachments.append(ImageAttachment(record["filename"], record["media_type"], data))
        if sum(len(item.data) for item in attachments) > 30 * 1024 * 1024:
            raise ValueError("Attachments exceed 30 MiB")
        return attachments

    def _check_snapshot(self, snapshot):
        project = self.projects.raw_project(snapshot["project_id"])
        old = snapshot["project"]
        if any(project.get(k) != old.get(k) for k in ("active_version_id", "confirmed_spec", "target_mode", "plc_model")):
            raise ConflictError("任务执行期间工程状态已变化，请根据当前版本重新提出候选。")
        version = snapshot.get("version")
        if version and self.projects.raw_version(project["id"], version["id"]) != version:
            raise ConflictError("任务绑定的基础版本已变化。")
        if snapshot.get("program_ir") is not None:
            if canonical_hash(self.projects.program(project["id"], version["id"])) != canonical_hash(snapshot["program_ir"]):
                raise ConflictError("任务绑定的程序内容已变化。")
        if snapshot.get("fbd_baseline") is not None:
            current = self.projects.artifact(project["id"], version["id"], "gxw").read_bytes()
            if current != base64.b64decode(snapshot["fbd_baseline"]):
                raise ConflictError("任务绑定的 GXW 工程已变化。")

    def output(self, job_id):
        if not self.jobs:
            raise KeyError("No job outputs in read-only mode")
        self.jobs.get(job_id)
        path = contained(self.state_dir / "outputs" / (record_id(job_id) + ".json"), self.state_dir)
        if not path.is_file():
            raise KeyError("No output is available yet")
        output = read_json(path)
        if isinstance(output, dict) and isinstance(output.get("analysis"), dict):
            from confirmed_spec import restore_review_choices
            if isinstance(output.get("spec_draft"), dict):
                output["spec_draft"] = restore_review_choices(output["spec_draft"], output["analysis"])
        return public(output)

    def submit(self, command):
        self.writable()
        # Retry identity is the original HTTP command, not a newly observed
        # project/model snapshot. This also avoids reopening credentials on retry.
        request_key = hashlib.sha256(command["request_id"].encode()).hexdigest()
        path = self.state_dir / "job_commands" / (request_key + ".json")
        digest = canonical_hash(command)
        with self.lock.thread_lock:
            if path.exists():
                saved = read_json(path)
                if saved["command_hash"] != digest:
                    raise ConflictError("Request ID is already bound to another command")
                return self.jobs.get(saved["job_id"])
            job = self._submit_job(command)
            atomic_json(path, {"command_hash": digest, "job_id": job["id"]})
            return job

    def _submit_job(self, command):
        self.writable()
        project_id = command["project_id"]
        with self.lock.thread_lock:
            context = self.projects.tool_context(project_id, command.get("version_id"))
            project = dict(context.project)
            snapshot = {**copy.deepcopy(command), "project": project, "version": context.version,
                        "version_id": context.version_id or None, "program_ir": context.program_ir}
            if context.version and context.version.get("target_mode") == "fbd":
                raw = self.projects.artifact(project_id, context.version_id, "gxw").read_bytes()
                snapshot["fbd_baseline"] = base64.b64encode(raw).decode("ascii")
                snapshot["fbd_program"] = context.version.get("program_name")
            # Resolve files and credentials at submission, never later from mutable UI state.
            images = self._attachments(project_id, command.get("attachment_ids", []))
            requires_model = command["kind"] not in ("gx_read", "gx_inspect") and (command["kind"] != "review" or command.get("deep", True))
            provider, model = self.model_factory() if requires_model else (None, {})
            snapshot["model"] = model
            if command["kind"] == "debug_plan":
                snapshot["saved_run"] = self.projects.simulator_run(project_id, context.version_id, command.get("run_id"))

        def worker(ctx):
            if command["kind"] in ("gx_read", "gx_inspect"):
                return self._read_gx(ctx, snapshot)
            from api import provider_scope
            from i18n import language_context
            from model_provider import response_policy_scope
            from application.model_progress import ModelJobContext, ModelProgressReporter
            ctx.checkpoint()
            model_context = ModelJobContext(ctx)
            model_progress = ModelProgressReporter(model_context)
            with language_context(snapshot["response_language"]), provider_scope(provider, model_name=model.get("model")), response_policy_scope(
                    enforce_language=False, on_progress=model_progress, on_preview=model_progress.preview):
                try:
                    result = self._run_job(model_context, snapshot, context, images, provider)
                finally:
                    model_context.flush()
            return result
        return self.jobs.submit(command["kind"], snapshot, worker, request_id=command["request_id"])

    def _read_gx(self, ctx, snapshot):
        with self.lock.thread_lock:
            ctx.checkpoint()
            self._check_snapshot(snapshot)
            result = self.execution.submit_read("read_gx" if snapshot["kind"] == "gx_read" else "inspect_gx",
                {"project_id": snapshot["project_id"], "version_id": snapshot["version_id"]},
                progress=lambda *values: ctx.emit("progress", {"message": str(values[-1])})).result()
            output = public(result)
            if result.get("_candidate_ir"):
                candidate = self._with_candidate_diff(snapshot["project_id"], snapshot["version_id"],
                    {"_candidate_ir": result["_candidate_ir"], "_confirmed_spec": result.get("_confirmed_spec"), "target_mode": "ladder"})
                proposal = self.proposals.create("accept_local", snapshot["project_id"],
                    candidate,
                    public_summary={"summary": "从 GX Works2 读取的程序，接受后保存为本地版本", "diff": self._diff_summary(candidate["_preview_diff"])},
                    base_version_id=snapshot["version_id"], request_id=ctx.job_id)
                output["proposal_id"] = proposal["id"]
            atomic_json(self.state_dir / "outputs" / (ctx.job_id + ".json"), output)
            return {"status": result.get("status"), "proposal_id": output.get("proposal_id"), "passed": False}

    def _run_job(self, ctx, snapshot, context, images, provider):
        kind, project_id, text = snapshot["kind"], snapshot["project_id"], snapshot.get("text", "")
        project, version = snapshot["project"], snapshot.get("version")
        language = snapshot["response_language"]
        output = None
        if kind == "analysis":
            from api import analyze_requirement_streaming
            from confirmed_spec import build_review_draft
            ctx.emit("progress", {"message": "正在分析需求"})
            analysis = analyze_requirement_streaming(text, confirmed_spec=project.get("confirmed_spec"),
                conversation_history=project.get("messages", []), image_attachments=images,
                on_reasoning_chunk=lambda t: ctx.emit("reasoning", {"text": t}),
                on_content_chunk=lambda t: ctx.emit("content", {"text": t}), response_language=language,
                on_format_repair=lambda: ctx.emit("progress", {"message": "正在修正需求分析的回复格式"}))
            if not isinstance(analysis, dict):
                raise ValueError("需求分析未完成。")
            output = {"analysis": analysis, "spec_draft": build_review_draft(analysis, project.get("confirmed_spec")),
                      "spec_base_hash": public_spec_hash(project.get("confirmed_spec")), "base_version_id": snapshot.get("version_id")}
        elif kind == "generation":
            from application.generation import GenerationRequest, GenerationWorkflow, GenerationDependencies
            from plc_ir import ir_to_ladder
            out_dir = self.state_dir / "staging" / ctx.job_id
            if project["target_mode"] == "fbd" or (version or {}).get("target_mode") == "fbd":
                from application.fbd import generate_candidate
                fbd_payload = generate_candidate(out_dir, snapshot, images, ctx)
                metadata = fbd_payload["metadata"]
                metadata["artifacts"] = {k: v["path"] for k, v in fbd_payload["artifacts"].items()}
            else:
                program = snapshot.get("program_ir")
                request = GenerationRequest(user_input=text, effort=project.get("effort"), target_mode=project["target_mode"],
                    previous_json=ir_to_ladder(program) if program else None, previous_ir=program,
                    confirmed_context=project.get("confirmed_spec"), conversation_history=project.get("messages", []),
                    plc_model=project.get("plc_model", "FX3U"), revision=(program or {}).get("revision", 0) + 1,
                    requirement_text=text, image_attachments=images, model_name=snapshot.get("model", {}).get("model"), response_language=language)
                metadata = GenerationWorkflow(request, out_dir, ctx.emit, GenerationDependencies(provider=provider)).run()
            ctx.checkpoint()
            output = {"generation": metadata}
            if metadata.get("contract_mismatch"):
                output["status"] = "contract_mismatch"
                atomic_json(self.state_dir / "outputs" / (ctx.job_id + ".json"), output)
                return {"status": "contract_mismatch", "summary": "候选与确认规格存在冲突，请检查诊断。"}
            payload = {"project_id": project_id, "target_mode": metadata["target_mode"],
                       "plc_model": project.get("plc_model", "FX3U"), "_confirmed_spec": project.get("confirmed_spec")}
            if metadata["target_mode"] == "ladder":
                payload["_candidate_ir"] = json.loads((out_dir / metadata["artifacts"]["ir"]).read_text(encoding="utf-8"))
            else:
                payload.update(staging_dir=str(out_dir), metadata=metadata, artifacts={k: {
                    "path": v, "sha256": hashlib.sha256((out_dir / v).read_bytes()).hexdigest()}
                    for k, v in metadata["artifacts"].items()})
            with self.lock.thread_lock:
                self._check_snapshot(snapshot)
                payload = self._with_candidate_diff(project_id, (version or {}).get("id"), payload)
                proposal = self.proposals.create("accept_local", project_id, payload,
                    public_summary={"summary": text[:500], "validation": metadata["validation"], "diff": self._diff_summary(payload["_preview_diff"])},
                    base_version_id=(version or {}).get("id"), request_id=ctx.job_id)
            output["proposal_id"] = proposal["id"]
        elif kind == "agent":
            from plc_agent import run_tool_agent
            result = run_tool_agent(text, context=context, runtime=self.projects.runtime, provider=provider,
                conversation_history=project.get("messages", []), response_language=language,
                on_progress=lambda m: ctx.emit("progress", {"message": m}),
                on_reasoning_chunk=lambda t: ctx.emit("reasoning", {"text": t}),
                on_content_chunk=lambda t: ctx.emit("content", {"text": t}))
            ctx.checkpoint()
            with self.lock.thread_lock:
                self._check_snapshot(snapshot)
                proposals = [self._pending_proposal(p, f"{ctx.job_id}_{i}", base_version_id=snapshot.get("version_id"))
                             for i, p in enumerate(result.pending_actions)]
                self.store.add_message(project_id, "assistant", result.content, kind="agent")
            output = {"content": result.content, "audit": result.audit, "proposal_ids": [p["id"] for p in proposals]}
        else:
            output = self._plan_or_review(ctx, snapshot, provider)
        atomic_json(self.state_dir / "outputs" / (ctx.job_id + ".json"), output)
        return {key: output[key] for key in ("proposal_id", "proposal_ids", "report_id", "plan_id", "status") if key in output}

    def _plan_or_review(self, ctx, snapshot, provider):
        # Pure workflow services are imported only when requested. Their signatures
        # are kept here, outside HTTP routes, to share them with the Qt adapters.
        from application.review import InspectionWorkflow
        from application.planning import SimulatorTestPlanWorkflow, EvidenceDebugPlanWorkflow
        from plc_ir import ir_to_ladder
        project, version, program = snapshot["project"], snapshot.get("version"), snapshot.get("program_ir")
        if not version or not program:
            raise ValueError("当前版本没有可用于检查或测试的 PLC IR。")
        project_id, version_id = project["id"], version["id"]
        common = {"on_event": ctx.emit, "response_language": snapshot["response_language"],
                  "provider": provider, "model_name": snapshot.get("model", {}).get("model"),
                  "effort": project.get("effort"), "program_ir": program}
        def before_save():
            ctx.checkpoint()
            self._check_snapshot(snapshot)
        if snapshot["kind"] == "review":
            report = InspectionWorkflow(ctx.job_id, "program_review", snapshot.get("text", ""), ir_to_ladder(program),
                version_id, project.get("plc_model", "FX3U"), project_id=project_id,
                confirmed_spec=project.get("confirmed_spec"), deep=snapshot.get("deep", True), **common).run()
            with self.lock.thread_lock:
                before_save()
                report = self.store.create_report(project_id, report)
            return {"report_id": report["report_id"], "report": report}
        common.update(before_save=before_save, write_lock=self.lock.thread_lock)
        if snapshot["kind"] == "test_plan":
            plan = SimulatorTestPlanWorkflow(ctx.job_id, self.store, project_id, version_id, **common).run()
        else:
            store = _SnapshotStore(self.store, snapshot)
            plan = EvidenceDebugPlanWorkflow(ctx.job_id, store, project_id, version_id, snapshot["run_id"],
                saved_run=snapshot["saved_run"], **common).run()
        return {"plan_id": plan["plan_id"], "plan": plan}

    def _pending_proposal(self, pending, request_id, *, base_version_id=None):
        kind = pending.get("type")
        if kind in ("accept_candidate_patch", "accept_generated_program"):
            action = "accept_local"
        elif kind == "import_current_program_to_gxworks2":
            action = "gx_import"
        else:
            raise ValueError("Unsupported pending engineering action")
        base_id = pending.get("base_version_id") or pending.get("version_id") or base_version_id
        payload = self._with_candidate_diff(pending["project_id"], base_id, pending) if action == "accept_local" else dict(pending)
        return self.proposals.create(action, pending["project_id"], payload,
            public_summary={"summary": "Agent 提出的工程操作", "diff": self._diff_summary(payload["_preview_diff"]) if "_preview_diff" in payload else pending.get("diff"), "validation": pending.get("validation")},
            base_version_id=base_id, request_id=request_id)

    def agent_call(self, command):
        self.writable()
        request_key = hashlib.sha256((command["project_id"] + ":" + command["call_id"]).encode()).hexdigest()
        path = self.state_dir / "agent_calls" / (request_key + ".json")
        digest = canonical_hash(command)
        with self.lock.thread_lock:
            if path.exists():
                saved = read_json(path)
                if saved["input_hash"] != digest:
                    raise ConflictError("Agent call ID was already used with other arguments")
                return saved["response"]
            context = self.projects.tool_context(command["project_id"], command.get("version_id"))
            result = self.projects.runtime.invoke(ToolCall(command["call_id"], command["name"], command.get("arguments", {})), context)
            envelope = public_tool_result_data(result)
            response = {"data": envelope, "content": json.dumps(envelope, ensure_ascii=False), "is_error": result.is_error,
                        "call_id": command["call_id"], "name": command["name"]}
            pending = (result.data.get("data") or {}).get("pending_action")
            if not result.is_error and result.data.get("status") == "confirmation_required" and pending:
                proposal = self._pending_proposal(pending, request_key, base_version_id=context.version_id or None)
                response["proposal_id"] = proposal["id"]
            atomic_json(path, {"input_hash": digest, "response": response})
            return response

    def execution_proposal(self, command):
        self.writable()
        project_id, version_id = command["project_id"], command["version_id"]
        with self.lock.thread_lock:
            self.projects.raw_version(project_id, version_id)
            payload = {"project_id": project_id, "version_id": version_id}
            plan_id = command.get("plan_id")
            if command["action"] in ("simulation", "debug"):
                record_id(plan_id)
                plan = self.projects.plan(project_id, version_id, plan_id, kind=command["action"])
                payload["plan"] = plan
            return self.proposals.create(command["action"], project_id, payload,
                public_summary={"summary": {"gx_import": "将指定版本导入 GX Works2", "simulation": "导入指定版本并运行指定仿真方案", "debug": "执行指定调试方案"}[command["action"]],
                                "version_id": version_id, "plan_id": plan_id},
                base_version_id=version_id, request_id=command["request_id"])

    def decide(self, proposal_id, decision):
        self.writable()
        proposal = self.proposals.get(proposal_id)
        if decision == "reject":
            return {"proposal": self.proposals.reject(proposal_id)}
        if proposal["action"] == "accept_local":
            return {"proposal": self.proposals.accept(proposal_id)}
        def worker(ctx):
            # A cancel request while waiting for the engineering lock is still
            # before any external effect and must be honored after acquiring it.
            with self.lock.thread_lock:
                ctx.checkpoint()
                result = self.proposals.accept(proposal_id, executor=lambda payload, approved_id:
                    self.execution.submit_approved({"gx_import": "import_gx", "simulation": "simulate", "debug": "debug"}[proposal["action"]],
                        payload, approval_id=approved_id,
                        progress=lambda *m: ctx.emit("progress", {"message": str(m[-1])})).result())
            return {"proposal_id": proposal_id, "status": result["status"], "result": result.get("result")}
        return {"job": self.jobs.submit("execution", {"project_id": proposal["project_id"], "version_id": proposal["base_version_id"],
                    "proposal_id": proposal_id}, worker, request_id="approve_" + proposal_id)}

    def _candidate_diff(self, project_id, base_version_id, payload):
        """Review the proposal's bound version, never the UI's active selection."""
        if "_candidate_ir" in payload:
            from plc_core import PLCCore
            before = self.projects.program(project_id, base_version_id) if base_version_id else None
            expected = payload.get("base_ir_sha256")
            if expected and canonical_hash(before) != expected:
                raise ConflictError("The proposal's base program changed")
            result = dict(PLCCore().diff_programs(before, payload["_candidate_ir"]))
        elif payload.get("target_mode") == "fbd":
            from application.fbd import graph_diff, staged_bytes
            before = None
            if base_version_id and self.projects.raw_version(project_id, base_version_id)["target_mode"] == "fbd":
                before = self.projects.program(project_id, base_version_id)
            after = json.loads(staged_bytes(payload, self.state_dir)["fbd"])
            result = graph_diff(before, after)
        elif payload.get("target_mode") == "st":
            from difflib import unified_diff
            before = ""
            if base_version_id:
                base = self.projects.raw_version(project_id, base_version_id)
                artifact_id = "st" if "st" in (base.get("artifacts") or {}) else "st_from_ir"
                before = self.projects.artifact(project_id, base_version_id, artifact_id).read_text(encoding="utf-8")
            root = contained(Path(payload["staging_dir"]), self.state_dir)
            entry = payload["artifacts"]["st"]
            data = contained(root / entry["path"], root).read_bytes()
            if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise ConflictError("Staged candidate changed")
            after = data.decode("utf-8")
            lines = unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                fromfile=f"{base_version_id or 'empty'}/program.st", tofile="candidate/program.st")
            result = {"kind": "st", "has_changes": before != after, "before": before, "after": after,
                "unified_diff": "".join(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n" for line in lines)}
        else:
            raise ValueError("Candidate has no reviewable program")
        result["base_version_id"] = base_version_id
        return result

    @staticmethod
    def _diff_summary(diff):
        if diff["kind"] == "fbd":
            return {key: value for key, value in diff.items() if key != "unified_diff"}
        if diff["kind"] == "st":
            return {"kind": "st", "modified": ["program.st"] if diff["has_changes"] else []}
        summary = {key: diff[key] for key in ("kind", "added", "deleted", "modified", "device_comments_changed",
                    "before_network_count", "after_network_count")}
        summary["changes"] = [{key: change[key] for key in ("marker", "network", "comment", "instruction_count")}
                              for change in diff["changes"]]
        return summary

    def _with_candidate_diff(self, project_id, base_version_id, payload):
        payload = copy.deepcopy(payload)
        # Freeze review data inside the hash-bound private payload. Reopening an
        # accepted or stale proposal therefore still displays its original base.
        payload["_preview_diff"] = self._candidate_diff(project_id, base_version_id, payload)
        return payload

    def proposal_preview(self, proposal_id, *, theme=None):
        from plc_ir import ir_to_ladder
        record = self.proposals.get(proposal_id)
        payload = self.proposals.read_private(proposal_id)
        if payload.get("target_mode") == "fbd":
            from application.fbd import staged_bytes
            artifacts = staged_bytes(payload, self.state_dir)
            return {"target_mode": "fbd", "program": public(json.loads(artifacts["fbd"])),
                    "svg": artifacts["svg"].decode("utf-8"), "diff": public(payload["_preview_diff"])}
        if "_candidate_ir" in payload:
            from plc_core import PLCCore
            program = payload["_candidate_ir"]
            # Managed, deterministic previews; no transient file names cross HTTP.
            root = self.state_dir / "previews" / proposal_id
            with self.lock.thread_lock:
                if not (root / "ladder.svg").is_file():
                    PLCCore().compile_project(program, root)
            return {"target_mode": "ladder", "ladder": ir_to_ladder(program), "program": public(program),
                    "svg": self.projects.themed_svg((root / "ladder.svg").read_text(encoding="utf-8"), theme),
                    "st": (root / "program_from_ir.st").read_text(encoding="utf-8"),
                    "diff": public(payload.get("_preview_diff") or self._candidate_diff(record["project_id"], record["base_version_id"], payload))}
        if payload.get("target_mode") == "st":
            entry = payload["artifacts"]["st"]
            path = contained(Path(payload["staging_dir"]) / entry["path"], self.state_dir)
            return {"target_mode": "st", "st": path.read_text(encoding="utf-8"),
                    "diff": public(payload.get("_preview_diff") or self._candidate_diff(record["project_id"], record["base_version_id"], payload))}
        version_id = record["base_version_id"]
        if not version_id or payload.get("version_id", version_id) != version_id:
            raise ConflictError("Execution proposal has no consistent bound version")
        with self.lock.thread_lock:
            project_id = record["project_id"]
            version = self.projects.version(project_id, version_id)
            artifacts = {item["id"] for item in version["artifacts"]}
            mode = version["target_mode"]
            program = self.projects.program(project_id, version_id) if mode in ("ladder", "fbd") else None
            if mode in ("ladder", "fbd") and program is None:
                raise ValueError("The execution proposal's program is unavailable")
            svg = self.projects.svg_preview(project_id, version_id, theme=theme) if "svg" in artifacts else None
            st_id = "st" if mode == "st" else "st_from_ir" if "st_from_ir" in artifacts else "st"
            st = self.projects.artifact(project_id, version_id, st_id).read_text(encoding="utf-8") if st_id in artifacts else None
            if mode == "st" and st is None:
                raise ValueError("The execution proposal's ST artifact is unavailable")
            return {"action": record["action"], "version_id": version_id, "version": version, "target_mode": mode,
                    "program": public(program), "svg": svg, "st": st, "plan": public(payload.get("plan"))}


def sfc_requirement(steps):
    return "\n".join(f"步骤 {i + 1}：{s['name']}\n动作：{s['action']}\n转移条件：{s.get('transition') or '流程结束'}" for i, s in enumerate(steps))


def public_spec_hash(spec):
    from plc_ir import canonical_sha256
    return canonical_sha256(spec) if spec is not None else None


class _SnapshotStore:
    """Frozen read side for multi-stage planning; writes use the owned store."""
    def __init__(self, store, snapshot):
        self._store, self._snapshot = store, copy.deepcopy(snapshot)

    def __getattr__(self, name):
        return getattr(self._store, name)

    def get_project(self, project_id):
        if project_id != self._snapshot["project_id"]:
            raise ValueError("Project is outside the job snapshot")
        return copy.deepcopy(self._snapshot["project"])

    def get_version(self, project_id, version_id):
        self.get_project(project_id)
        if version_id != self._snapshot["version_id"]:
            raise ValueError("Version is outside the job snapshot")
        return copy.deepcopy(self._snapshot["version"])

    def load_program_ir(self, project_id, version_id, **kwargs):
        self.get_version(project_id, version_id)
        return copy.deepcopy(self._snapshot["program_ir"])

    def load_simulator_run(self, project_id, version_id, run_id):
        self.get_version(project_id, version_id)
        if run_id != self._snapshot["run_id"]:
            raise ValueError("Run is outside the job snapshot")
        return copy.deepcopy(self._snapshot["saved_run"])
