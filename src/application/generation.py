"""Synchronous generation orchestration shared by desktop and local services.

No GUI, workspace activation, GX automation or simulator operations belong here.
Model response acceptance remains inside api/collect_response before callbacks.
"""
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Callable, Optional
import copy
import hashlib

import api
from application.base import model_call
from application.jobs import JobCancelled
from application.generation_repair import (
    GenerationError, GenerationValidationError, materialize_partial,
    check_candidate_containers,
)
from i18n import get_language, language_context, tr
from config_manager import get_active_model_name, load_full_config
from contract_repair import patch_device_addresses
from ladder_repair import (
    normalize_app_instr_out_outputs, normalize_legacy_counter_outputs,
)
from plc_json_validator import (
    PLCJsonValidationError, validate_ladder_candidate_structure,
    validate_ladder_partial_structure, validate_st_json,
)
from plc_ir import (
    IR_SCHEMA_VERSION, PLCIRValidationError, build_plc_ir, canonical_sha256,
    ir_to_ladder, is_plc_ir, validate_plc_ir,
)


@dataclass(frozen=True)
class GenerationRequest:
    """Caller-owned inputs are copied before a job crosses a thread boundary."""
    user_input: str
    effort: Optional[str] = None
    target_mode: str = "ladder"
    previous_json: object = None
    conversation_history: object = None
    confirmed_context: object = None
    task_type: Optional[str] = None
    current_version_json: object = None
    previous_ir: object = None
    plc_model: str = "FX3U"
    program_name: str = "MAIN"
    revision: int = 1
    requirement_text: str = ""
    repair_mode: bool = False
    allowed_rung_ids: object = None
    allowed_addresses: object = None
    image_attachments: object = None
    model_name: Optional[str] = None
    response_language: Optional[str] = None

    def __post_init__(self):
        for item in fields(self):
            object.__setattr__(self, item.name, copy.deepcopy(getattr(self, item.name)))
        object.__setattr__(self, "response_language", self.response_language or get_language())


@dataclass(frozen=True)
class GenerationDependencies:
    """Inject model calls or a provider snapshot; defaults use the accepted API."""
    stream_response: Optional[Callable] = None
    generate_json: Optional[Callable] = None
    provider: object = None
    check_cancelled: Optional[Callable] = None
    preserve_rejected_candidate: bool = False



class GenerationWorkflow:
    def __init__(self, request, output_dir, on_event=None, dependencies=None):
        self.request = copy.deepcopy(request)
        for item in fields(self.request):
            setattr(self, item.name, copy.deepcopy(getattr(self.request, item.name)))
        self.output_dir = Path(output_dir)
        self.on_event = on_event
        self.dependencies = dependencies or GenerationDependencies()
        self.conversation_history = self.conversation_history or []
        self.task_type = self.task_type or ("edit" if self.previous_json is not None else "generate")
        # The local merge base must also be visible to the model. Previously an
        # edit request set ``is_edit_mode`` but omitted the current ladder from
        # model context, so the model often regenerated the program from spec.
        if self.current_version_json is None and self.previous_json is not None:
            self.current_version_json = copy.deepcopy(self.previous_json)
        self.previous_ir = self.previous_ir if is_plc_ir(self.previous_ir) else None
        self.plc_model = str(self.plc_model or "FX3U").upper()
        self.program_name = str(self.program_name or "MAIN").strip() or "MAIN"
        self.requirement_text = str(self.requirement_text or self.user_input or "")
        try:
            self.revision = max(0, int(self.revision))
        except (TypeError, ValueError):
            self.revision = 1
        self.repair_mode = bool(self.repair_mode)
        self.allowed_rung_ids = {int(item) for item in (self.allowed_rung_ids or [])}
        self.allowed_addresses = {
            str(item).strip().upper()
            for item in (self.allowed_addresses or [])
            if str(item).strip()
        }
        self.image_attachments = tuple(self.image_attachments or ())
        if self.model_name is None:
            try:
                self.model_name = get_active_model_name(load_full_config())
            except Exception:
                self.model_name = None

    def _emit(self, event_type, payload):
        if self.dependencies.check_cancelled:
            self.dependencies.check_cancelled()
        if self.on_event:
            if not isinstance(payload, dict):
                payload = {"text": str(payload)}
            self.on_event(event_type, copy.deepcopy(payload))

    def run(self):
        """Build artifacts synchronously, returning their manifest or raising.

        The callback receives progress/reasoning/content events. Terminal state
        and event sequencing belong to the caller's task manager.
        """
        with language_context(self.response_language), api.provider_scope(
            self.dependencies.provider, model_name=self.model_name
        ):
            return self._run()

    def _run(self):
        """Generate one candidate and perform only transport/shape acceptance.

        Once the user has confirmed the specification, this workflow does not
        reinterpret that intent with approach heuristics, regex-derived semantic
        requirements, or hidden model repair loops.  Strong semantic/static
        checks remain available to Review, simulator and GX execution paths.
        """
        try:
            import json

            def emit_parsing_progress(message):
                self._emit("progress", {"stage": "parsing", "message": str(message)})

            self.output_dir.mkdir(parents=True, exist_ok=True)
            validation_messages = []
            repair_attempts = 0

            # Preserve only semantics that were explicitly stored as structured
            # confirmed data.  Do not infer new blocking requirements from prose.
            semantic_requirements = []
            if self.target_mode == "ladder" and isinstance(self.confirmed_context, dict):
                explicit = self.confirmed_context.get("execution_semantics")
                if isinstance(explicit, list):
                    from plc_semantics import normalize_semantic_requirements
                    semantic_requirements = normalize_semantic_requirements(explicit)

            # ---------- Phase 1: one model generation ----------
            full_content = ""
            streaming_succeeded = False
            is_edit_mode = self.target_mode == "ladder" and self.previous_json is not None
            model_user_input = self.user_input
            if self.target_mode == "ladder" and not self.repair_mode:
                output_discipline = (
                    '输出协议纪律：只返回协议允许的 JSON 字段，不要输出解释性正文。'
                    'debug_note 是可选字段，默认省略；不要用 debug_note 记录推理、修改原因或长说明。'
                    '已有 device_comments 无必要不要改写。label、debug_note、device_comment 单条文本目标不超过48字符，'
                    '硬上限64字符；返回前自行检查字段名和文本长度。\n\n'
                )
                if is_edit_mode:
                    # This is a model instruction, not an application-side gate.
                    # The parser deliberately continues to accept both partial and
                    # full JSON so an imperfect model choice never becomes another
                    # hard-validation failure or hidden retry loop.
                    model_user_input = (
                        output_discipline
                        + '这是对系统提供的 Current version JSON 的修改请求。除非用户明确要求整体重写，'
                        '优先返回 mode="partial"：device_comments 只列确实需要修改的注释，rungs 只列修改或新增的完整梯级，'
                        'delete_rung_ids 只列需要删除的梯级；不要重复输出未修改梯级。'
                        '如果你仍返回完整 JSON，应用也会正常接受，不需要为了格式选择重新生成。\n\n'
                        '用户修改要求：\n'
                        + self.user_input
                    )
                else:
                    model_user_input = output_discipline + '用户要求：\n' + self.user_input
            try:
                stream_model_response = self.dependencies.stream_response or api.stream_model_response

                def on_reasoning(token):
                    self._emit("reasoning", token)

                def on_content(token):
                    self._emit("content", token)

                self._emit("progress", {"stage": "connecting", "message": tr('正在连接模型')})
                _reasoning, full_content = model_call(
                    stream_model_response,
                    model_user_input,
                    self.model_name,
                    self.effort,
                    self.target_mode,
                    on_reasoning_chunk=on_reasoning,
                    on_content_chunk=on_content,
                    is_edit_mode=is_edit_mode,
                    conversation_history=self.conversation_history,
                    confirmed_context=self.confirmed_context,
                    persist_history=False,
                    task_type=self.task_type,
                    current_version_json=self.current_version_json,
                    plc_model=self.plc_model,
                    image_attachments=self.image_attachments,
                )
                emit_parsing_progress(tr('正在解析模型输出：清理流式文本'))
                streaming_succeeded = True
            except Exception as stream_err:
                from model_provider import ResponseRejectedError
                if isinstance(stream_err, (ResponseRejectedError, JobCancelled)):
                    raise
                self._emit("progress", {
                    "stage": "fallback",
                    "severity": "warning",
                    "message": tr('流式调用失败，切换普通模式：{v0}', v0=stream_err),
                })
                print(tr('流式调用失败，降级至普通模式: {v0}', v0=stream_err))

            # Transport fallback is not a semantic repair. It obtains the same
            # requested candidate once when streaming itself failed.
            if streaming_succeeded and full_content:
                json_str = full_content.strip()
                if json_str.startswith("```"):
                    json_str = json_str.split("\n", 1)[1]
                if json_str.endswith("```"):
                    json_str = json_str.rsplit("\n", 1)[0]
                json_str = json_str.strip()
            else:
                json_str = model_call(
                    self.dependencies.generate_json or api.generate_model_json,
                    model_user_input,
                    self.model_name,
                    self.effort,
                    self.target_mode,
                    is_edit_mode=is_edit_mode,
                    conversation_history=self.conversation_history,
                    confirmed_context=self.confirmed_context,
                    persist_history=False,
                    task_type=self.task_type,
                    current_version_json=self.current_version_json,
                    plc_model=self.plc_model,
                    image_attachments=self.image_attachments,
                )

            if not json_str:
                raise GenerationError(tr('大模型未返回合法数据'))

            def parse_candidate(candidate):
                emit_parsing_progress(tr('正在解析模型输出：读取 JSON 结构'))
                parsed = json.loads(candidate)
                if not isinstance(parsed, dict):
                    raise PLCJsonValidationError("$: expected JSON object")

                if self.target_mode == "ladder":
                    check_candidate_containers(parsed)
                    emit_parsing_progress(tr('正在解析模型输出：规范化梯形图协议'))
                    parsed, converted_counters = normalize_legacy_counter_outputs(parsed)
                    if converted_counters:
                        validation_messages.append(
                            tr('已将旧版 TIMER+C 计数器结构转换为 COUNTER：')
                            + ", ".join(converted_counters)
                        )
                    parsed, converted_outs = normalize_app_instr_out_outputs(parsed)
                    if converted_outs:
                        validation_messages.append(
                            tr('已将误放入 APP_INSTR 的 OUT 转换为标准输出结构：')
                            + "；".join(converted_outs)
                        )

                    # Explicit repair/debug tools keep their scope boundary, but
                    # direct generation never starts a hidden semantic repair.
                    if self.repair_mode:
                        if parsed.get("mode") != "partial":
                            raise PLCJsonValidationError('$.mode: repair must return "partial"')
                        changed_ids = {
                            int(rung.get("rung_id"))
                            for rung in parsed.get("rungs", [])
                            if rung.get("rung_id") is not None
                        }
                        changed_ids.update(int(item) for item in parsed.get("delete_rung_ids", []))
                        outside = changed_ids - self.allowed_rung_ids
                        if outside:
                            raise PLCJsonValidationError(
                                "$.rungs: repair changed evidence-external rung ids "
                                + ", ".join(map(str, sorted(outside)))
                            )
                        comment_addresses = {
                            str(item).strip().upper()
                            for item in parsed.get("device_comments", {})
                        }
                        outside_comments = comment_addresses - self.allowed_addresses
                        if outside_comments:
                            raise PLCJsonValidationError(
                                "$.device_comments: repair changed evidence-external addresses "
                                + ", ".join(sorted(outside_comments))
                            )
                        if self.task_type == "contract_repair":
                            if parsed.get("delete_rung_ids"):
                                raise PLCJsonValidationError(
                                    "$.delete_rung_ids: contract repair may not delete existing rungs"
                                )
                            if self.allowed_addresses:
                                referenced_addresses = patch_device_addresses(parsed)
                                outside_devices = referenced_addresses - self.allowed_addresses
                                if outside_devices:
                                    raise PLCJsonValidationError(
                                        "$.rungs: contract repair introduced out-of-scope devices "
                                        + ", ".join(sorted(outside_devices))
                                    )

                    if parsed.get("mode") == "partial":
                        if self.previous_json is None:
                            raise PLCJsonValidationError(
                                '$.mode: received "partial" without a previous ladder'
                            )
                        validate_ladder_partial_structure(parsed, plc_model=self.plc_model)
                        parsed = materialize_partial(self.previous_json, parsed)

                    if not parsed.get("rungs"):
                        raise PLCJsonValidationError("$.rungs: generated program must not be empty")
                    emit_parsing_progress(tr('正在解析模型输出：检查结构与地址'))
                    validate_ladder_candidate_structure(
                        parsed,
                        plc_model=self.plc_model,
                        require_catalogued_instructions=True,
                    )
                else:
                    emit_parsing_progress(tr('正在解析模型输出：校验 ST 结构'))
                    validate_st_json(parsed)
                return parsed

            def persist_repair_candidate():
                # Private staging only: only the operator Workbench opts into this.
                # Low-level workflows and explicit repair tools retain zero-artifact failure semantics.
                if not self.dependencies.preserve_rejected_candidate:
                    return
                if self.target_mode != "ladder" or not isinstance(json_str, str):
                    return
                if not json_str.strip() or len(json_str) > 512000:
                    return
                (self.output_dir / "repair_candidate.json").write_text(json_str, encoding="utf-8")

            validation_errors = (PLCJsonValidationError, PLCIRValidationError, json.JSONDecodeError)
            try:
                parsed_json = parse_candidate(json_str)
            except validation_errors as error:
                # No hidden semantic re-generation loop. Preserve the rejected
                # candidate privately so an operator can explicitly request one repair.
                persist_repair_candidate()
                raise GenerationValidationError(
                    [error], attempts=0, max_attempts=0, language=self.response_language,
                    stop_reason="final_validation",
                ) from error

            if self.target_mode == "ladder":
                emit_parsing_progress(tr('正在解析模型输出：构建 PLC IR'))
                program_ir = build_plc_ir(
                    parsed_json,
                    plc_model=self.plc_model,
                    program_name=self.program_name,
                    revision=self.revision,
                    confirmed_spec=self.confirmed_context,
                    semantic_requirements=semantic_requirements,
                )
                # IR validation here proves deterministic consistency only. It
                # deliberately does not re-judge the confirmed user intent.
                validate_plc_ir(program_ir, validate_ladder=False)
                self._emit("progress", {
                    "stage": "parsed",
                    "message": tr('模型输出已解析为候选程序'),
                })

                rendered_ladder = ir_to_ladder(program_ir)
                final_json_str = json.dumps(rendered_ladder, ensure_ascii=False, indent=2)
                json_path = self.output_dir / "ladder.json"
                json_path.write_text(final_json_str, encoding="utf-8")

                from plc_st_renderer import (
                    ST_RENDERER_SCHEMA_VERSION,
                    render_plc_ir_to_st,
                    validate_st_traceability,
                )
                st_from_ir = render_plc_ir_to_st(program_ir)
                validate_st_traceability(program_ir, st_from_ir)
                st_path = self.output_dir / "program_from_ir.st"
                st_path.write_text(st_from_ir, encoding="utf-8")
                ir_path = self.output_dir / "program.ir.json"
                ir_path.write_text(json.dumps(program_ir, ensure_ascii=False, indent=2), encoding="utf-8")

                from draw import AdvancedSVGLadder, generate_gx_works2_csv
                drawer = AdvancedSVGLadder()
                svg_content = drawer.generate_ladder(final_json_str)
                output_path = self.output_dir / "ladder.svg"
                output_path.write_text(svg_content, encoding="utf-8")

                artifacts = {
                    "json": json_path.name,
                    "ir": ir_path.name,
                    "svg": output_path.name,
                    "st_from_ir": st_path.name,
                }
                if self.plc_model == "FX3U":
                    program_csv = self.output_dir / "program.csv"
                    comment_csv = self.output_dir / "comments.csv"
                    generate_gx_works2_csv(program_ir, str(program_csv), str(comment_csv))
                    artifacts.update({"program_csv": program_csv.name, "comment_csv": comment_csv.name})

                from plc_semantics import SEMANTICS_SCHEMA_VERSION
                from plc_static_analyzer import STATIC_ANALYSIS_SCHEMA_VERSION
                from plc_timing import TIMING_ANALYSIS_SCHEMA_VERSION
                return {
                    "target_mode": "ladder",
                    "repair_attempts": repair_attempts,
                    "validation_profile": "generation_structural",
                    "program_name": self.program_name,
                    "revision": self.revision,
                    "ir_schema_version": IR_SCHEMA_VERSION,
                    "ir_sha256": canonical_sha256(program_ir),
                    "ladder_sha256": program_ir["source"]["ladder_sha256"],
                    "st_from_ir_sha256": hashlib.sha256(st_from_ir.encode("utf-8")).hexdigest(),
                    "st_renderer_schema_version": ST_RENDERER_SCHEMA_VERSION,
                    "semantic_schema_version": SEMANTICS_SCHEMA_VERSION,
                    "semantic_summary": {
                        "requirements": program_ir["logic"].get("requirements", []),
                        "coverage": program_ir["timing"].get("coverage", []),
                        "state_machine_count": len(program_ir["logic"].get("state_machines", [])),
                        "regions": [
                            {"code": region.get("code"), "kind": region.get("kind"),
                             "network_count": len(region.get("network_refs", []))}
                            for region in program_ir["logic"].get("regions", [])
                        ],
                    },
                    "static_analysis_schema_version": STATIC_ANALYSIS_SCHEMA_VERSION,
                    "static_analysis_summary": {
                        "counts": program_ir["analysis"].get("counts", {}),
                        "rules_checked": program_ir["analysis"].get("rules_checked", []),
                        "dependency_nodes": len(program_ir["analysis"].get("dependency_graph", {}).get("nodes", [])),
                        "dependency_edges": len(program_ir["analysis"].get("dependency_graph", {}).get("device_edges", [])),
                    },
                    "timing_analysis_schema_version": TIMING_ANALYSIS_SCHEMA_VERSION,
                    "timing_summary": {
                        "profile": program_ir["timing"].get("performance", {}).get("profile"),
                        "estimate": program_ir["timing"].get("performance", {}).get("estimate", {}),
                        "scan_budget": program_ir["timing"].get("performance", {}).get("scan_budget", {}),
                        "scan_monitor": program_ir["timing"].get("performance", {}).get("scan_monitor", {}),
                    },
                    "width": int(drawer.width),
                    "height": int(drawer.height),
                    "artifacts": artifacts,
                    "contract_mismatch": None,
                    "validation": {
                        "status": "candidate_ready",
                        "profile": "generation_structural",
                        "messages": validation_messages or [
                            tr('候选结构可解析；需求一致性不在生成阶段重复判定')
                        ],
                    },
                }

            st_text = parsed_json.get("st_code", "")
            if not st_text:
                st_text = json_str
            self._emit("progress", {"stage": "parsed", "message": tr('模型输出已解析为 ST 候选')})
            output_path = self.output_dir / "program.st"
            output_path.write_text(st_text.strip(), encoding="utf-8")
            return {
                "target_mode": "st",
                "validation_profile": "generation_structural",
                "width": 0,
                "height": 0,
                "artifacts": {"st": output_path.name},
                "validation": {
                    "status": "candidate_ready",
                    "profile": "generation_structural",
                    "messages": [tr('ST 输出结构可解析')],
                },
            }

        except (GenerationError, JobCancelled):
            raise
        except (PLCJsonValidationError, PLCIRValidationError) as error:
            try:
                persist_repair_candidate()
            except (NameError, OSError):
                pass
            raise GenerationValidationError(
                [error], attempts=0, max_attempts=0, language=self.response_language,
                stop_reason="final_validation",
            ) from error
        except Exception as error:
            raise GenerationError(tr('线程运行期异常: {v0}', v0=str(error))) from error
