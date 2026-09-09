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
from i18n import get_language, language_context, tr
from config_manager import get_active_model_name, load_full_config
from contract_repair import patch_device_addresses
from ladder_repair import (
    merge_duplicate_coils, normalize_app_instr_out_outputs,
    normalize_legacy_counter_outputs, normalize_m8029_parallel_branches,
)
from plc_json_validator import (
    ApproachContractValidationError, PLCJsonValidationError,
    validate_ladder_full, validate_ladder_partial, validate_st_json,
)
from plc_ir import (
    IR_SCHEMA_VERSION, apply_ladder_partial_to_ir, build_plc_ir,
    canonical_sha256, ir_to_ladder, is_plc_ir, validate_plc_ir,
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


class GenerationError(RuntimeError):
    """A rejected or invalid candidate; no project version has been activated."""


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
        try:
            import json

            def emit_parsing_progress(message):
                self._emit("progress", {"stage": "parsing", "message": str(message)})

            self.output_dir.mkdir(parents=True, exist_ok=True)
            validation_messages = []
            contract_mismatch = None
            semantic_requirements = []
            if self.target_mode == "ladder":
                from plc_semantics import semantic_requirements_from_spec

                semantic_requirements = semantic_requirements_from_spec(
                    self.confirmed_context,
                    self.requirement_text,
                )

            # ---------- Phase 1: 流式调用（含思考过程） ----------
            full_reasoning = ""
            full_content = ""
            streaming_succeeded = False
            is_edit_mode = self.target_mode == "ladder" and self.previous_json is not None

            try:
                stream_model_response = self.dependencies.stream_response or api.stream_model_response

                def on_reasoning(token):
                    self._emit("reasoning", token)

                def on_content(token):
                    self._emit("content", token)

                self._emit("progress", {"stage": "connecting", "message": tr('正在连接模型')})

                full_reasoning, full_content = model_call(stream_model_response,
                    self.user_input,
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
                if isinstance(stream_err, ResponseRejectedError):
                    raise
                self._emit("progress", {
                        "stage": "fallback",
                        "severity": "warning",
                        "message": tr('流式调用失败，切换普通模式：{v0}', v0=stream_err),
                    }
                )
                print(tr('流式调用失败，降级至普通模式: {v0}', v0=stream_err))

            # ---------- Phase 2: 获取最终 JSON ----------
            if streaming_succeeded and full_content:
                # 从流式输出中清洗 JSON
                json_str = full_content.strip()
                if json_str.startswith("```"):
                    json_str = json_str.split("\n", 1)[1]
                if json_str.endswith("```"):
                    json_str = json_str.rsplit("\n", 1)[0]
                json_str = json_str.strip()
            else:
                # 降级：使用普通非流式调用
                json_str = model_call(self.dependencies.generate_json or api.generate_model_json,
                    self.user_input, self.model_name, self.effort, self.target_mode,
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
                if self.target_mode == "ladder":
                    emit_parsing_progress(tr('正在解析模型输出：规范化梯形图结构'))
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
                if self.repair_mode:
                    if parsed.get("mode") != "partial":
                        raise PLCJsonValidationError(
                            '$.mode: repair must return "partial"'
                        )
                    changed_ids = {
                        int(rung.get("rung_id"))
                        for rung in parsed.get("rungs", [])
                        if rung.get("rung_id") is not None
                    }
                    changed_ids.update(
                        int(item) for item in parsed.get("delete_rung_ids", [])
                    )
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
                            "$.device_comments: repair changed evidence-external "
                            "addresses " + ", ".join(sorted(outside_comments))
                        )
                if self.repair_mode and self.task_type == "contract_repair":
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
                if self.target_mode == "ladder" and parsed.get("mode") == "partial":
                    validate_ladder_partial(parsed, plc_model=self.plc_model)
                    if self.previous_json is None:
                        raise PLCJsonValidationError(
                            '$.mode: received "partial" without a previous ladder'
                        )
                    base_ir = self.previous_ir or build_plc_ir(
                        self.previous_json,
                        plc_model=self.plc_model,
                        program_name=self.program_name,
                        revision=max(0, self.revision - 1),
                        confirmed_spec=self.confirmed_context,
                    )
                    patched_ir = apply_ladder_partial_to_ir(
                        base_ir,
                        parsed,
                        target_revision=self.revision,
                    )
                    parsed = ir_to_ladder(patched_ir)
                    print("Applied partial ladder update through PLC IR")
                return parsed

            def parse_and_validate(candidate):
                nonlocal contract_mismatch
                contract_mismatch = None
                parsed = parse_candidate(candidate)
                if self.target_mode == "ladder":
                    parsed, converted_counters = normalize_legacy_counter_outputs(parsed)
                    if converted_counters:
                        validation_messages.append(
                            tr('已兼容转换旧项目中的 TIMER+C：')
                            + ", ".join(converted_counters)
                        )
                    normalized_rungs = []
                    if not self.repair_mode and self.plc_model == "FX3U":
                        parsed, normalized_rungs = (
                            normalize_m8029_parallel_branches(parsed)
                        )
                    if normalized_rungs:
                        validation_messages.append(
                            tr('已将 M8029 完成触点规范化为应用指令的并联支路：')
                            + ", ".join(map(str, normalized_rungs))
                        )
                    emit_parsing_progress(tr('正在解析模型输出：执行 PLC 硬校验'))
                    try:
                        validate_ladder_full(
                            parsed,
                            plc_model=self.plc_model,
                            confirmed_spec=self.confirmed_context,
                        )
                    except ApproachContractValidationError as contract_error:
                        if self.task_type == "contract_repair":
                            raise
                        contract_mismatch = {
                            "message": str(contract_error),
                            "approach_name": contract_error.approach_name,
                            "issues": list(contract_error.issues),
                            "repairable": True,
                        }
                        validation_messages.append(str(contract_error))
                        self._emit("progress", {
                                "stage": "contract_mismatch",
                                "severity": "warning",
                                "message": (
                                    tr('方案约束未满足；保留原始候选并先生成 CSV，不会自动修复，等待用户决定。')
                                ),
                            },
                        )
                    if semantic_requirements:
                        from plc_semantics import strict_semantic_gaps

                        semantic_candidate = build_plc_ir(
                            parsed,
                            plc_model=self.plc_model,
                            program_name=self.program_name,
                            revision=self.revision,
                            confirmed_spec=self.confirmed_context,
                            semantic_requirements=semantic_requirements,
                        )
                        semantic_gaps = strict_semantic_gaps(semantic_candidate)
                        if semantic_gaps:
                            details = "; ".join(
                                f"{item.get('semantic')}({','.join(item.get('devices') or []) or tr('未指定设备')})"
                                for item in semantic_gaps
                            )
                            raise PLCJsonValidationError(
                                tr('扫描周期语义未满足：') + details
                            )
                else:
                    emit_parsing_progress(tr('正在解析模型输出：校验 ST 结构'))
                    validate_st_json(parsed)
                return parsed

            try:
                parsed_json = parse_and_validate(json_str)
            except Exception as first_err:
                if self.task_type == "contract_repair":
                    raise GenerationError(tr('方案约束修复候选未通过验证，不会继续隐藏重试: {v0}', v0=first_err),
                    )
                if self.target_mode != "ladder":
                    raise GenerationError(tr('模型输出 JSON 校验失败: {v0}', v0=first_err)
                    )

                print(tr('模型首轮输出未通过硬校验，自动纠错一次: {v0}', v0=first_err))
                validation_messages.append(str(first_err))
                self._emit("progress", {
                        "stage": "repairing",
                        "severity": "warning",
                        "message": tr('硬校验未通过，正在自动修复：{v0}', v0=first_err),
                    }
                )
                repair_source_json = json_str
                local_repair_succeeded = False
                try:
                    local_candidate = parse_candidate(json_str)
                    if self.repair_mode:
                        repaired_addresses = []
                    else:
                        local_candidate, repaired_addresses = merge_duplicate_coils(
                            local_candidate
                        )
                    if repaired_addresses:
                        local_candidate, normalized_rungs = (
                            normalize_m8029_parallel_branches(local_candidate)
                        )
                        if normalized_rungs:
                            validation_messages.append(
                                tr('本地修复时同步规范化 M8029 并联梯级：')
                                + ", ".join(map(str, normalized_rungs))
                            )
                        validate_ladder_full(
                            local_candidate,
                            plc_model=self.plc_model,
                            confirmed_spec=self.confirmed_context,
                        )
                        parsed_json = local_candidate
                        repaired_text = ", ".join(repaired_addresses)
                        validation_messages.append(
                            tr('本地自动合并重复线圈：{v0}', v0=repaired_text)
                        )
                        self._emit("progress", {
                                "stage": "repaired_local",
                                "message": (
                                    tr('本地自动修复完成：已将重复线圈 {v0} 合并为单一 COIL', v0=repaired_text)
                                ),
                            },
                        )
                        local_repair_succeeded = True
                except Exception:
                    if "local_candidate" in locals():
                        repair_source_json = json.dumps(
                            local_candidate,
                            ensure_ascii=False,
                        )

                if not local_repair_succeeded:
                    self._emit("progress", {
                            "stage": "repairing_remote",
                            "severity": "warning",
                            "message": tr('正在请求 AI 修复，最长等待 120 秒'),
                        },
                    )

                model_specific_rules = (
                    '3. FX3U 的 D8340 等定位寄存器按32位寄存器对处理，SFTL/SFTLP 源和目标不得重叠，M8029 与定位指令必须位于同一 rung 的并联分支。'
                    if self.plc_model == "FX3U"
                    else
                    '3. 按 FX5U 型号资料使用十进制 X/Y、SM/SD 特殊软元件和对应定位完成规则，不得套用 FX3U 专用寄存器对规则。'
                )
                output_rule = (
                    tr('必须返回 mode="partial"，且只能包含允许修复的梯级和地址。')
                    if self.repair_mode
                    else tr('增量编辑可返回合法 partial，否则返回完整 JSON。')
                )
                correction_request = '\n上一版梯形图 JSON 未通过程序硬校验。只返回修正后的 JSON，不要解释。\n\n目标 PLC：{v0}\n校验错误：\n{v1}\n\n必须遵守：\n1. 同一 Y/M 地址在整个最终程序中只能出现一次 COIL；即使位于同一梯级的不同 branch，也仍是双线圈。\n2. 多个驱动条件必须放入一个 parallel_block，汇合后只连接一个 COIL。\n{v2}\n4. 用户明确标注常开/常闭时，JSON 必须分别使用 NO/NC，不得自行反转。\n5. 保持用户确认的地址、参数和方案不变；型号规则冲突时采用等价合法实现并在 debug_note 标明。\n6. 禁止在 parallel_block 的 branches 内再次嵌套 parallel_block。\n7. TIMER 只能使用 T 地址、COUNTER 只能使用 C 地址；M8000/SM8000 持续使能的 TIMER 不能作为闪烁振荡器。\n8. 禁止用同一边沿下的 NC Mx→SET Mx 与 NO Mx→RST Mx 两分支模拟 ALT；改用两个明确相位及各自的定时器/状态转换。\n9. 校验错误若包含扫描周期语义：RISING_EDGE/FALLING_EDGE 必须使用对应边沿触点，FIRST_SCAN 必须使用目标 PLC 的首扫继电器，CYCLIC/INTERRUPT 必须保留对应执行源；不得用普通电平触点冒充。\n10. 用户选定方案的 generation_contract 是硬约束；必须补齐其中必用指令、软元件和结构，移除禁用项。不得换成另一个“功能等价”方案。\n11. generation_contract 中的 OUT 由 COIL/TIMER/COUNTER 输出结构满足，禁止写成 APP_INSTR OUT。RD3A/WR3A 虽是真实指令，但只能用于其手册支持的 FX0N-3A/FX2N-2AD/2DA，不得套用于 FX3U-4AD-ADP/4DA-ADP。\n\n请修复你紧邻此消息之前返回的 JSON。{v3}\n'.format(v0=self.plc_model, v1=first_err, v2=model_specific_rules, v3=output_rule).strip()
                retry_json = (
                    json.dumps(parsed_json, ensure_ascii=False)
                    if local_repair_succeeded
                    else model_call(self.dependencies.generate_json or api.generate_model_json,
                    correction_request,
                    self.model_name,
                    "high",
                    self.target_mode,
                    is_edit_mode=is_edit_mode,
                    conversation_history=[
                        *self.conversation_history,
                        {"role": "user", "content": self.user_input},
                        {"role": "assistant", "content": repair_source_json},
                    ],
                    confirmed_context=self.confirmed_context,
                    persist_history=False,
                    request_timeout=120,
                    max_retries=0,
                    raise_errors=True,
                    task_type="repair" if self.repair_mode else "debug",
                    current_version_json=self.current_version_json,
                    plc_model=self.plc_model,
                )
                )
                if not retry_json:
                    raise GenerationError(tr('模型输出校验失败且自动纠错无返回: {v0}', v0=first_err),
                    )
                try:
                    parsed_json = parse_and_validate(retry_json)
                    print(tr('自动纠错后的 JSON 已通过硬校验'))
                    validation_messages.append(tr('自动修复后已通过全部硬校验'))
                except Exception as retry_err:
                    raise GenerationError(tr('模型输出连续两次未通过硬校验: 首次={v0}; 重试={v1}', v0=first_err, v1=retry_err)
                    )

            # 将最终 JSON 写入磁盘
            if self.target_mode == "ladder":
                emit_parsing_progress(tr('正在解析模型输出：构建并校验 PLC IR'))
                program_ir = build_plc_ir(
                    parsed_json,
                    plc_model=self.plc_model,
                    program_name=self.program_name,
                    revision=self.revision,
                    confirmed_spec=self.confirmed_context,
                    semantic_requirements=semantic_requirements,
                )
                validate_plc_ir(
                    program_ir,
                    confirmed_spec=(
                        None
                        if contract_mismatch
                        and self.task_type != "contract_repair"
                        else self.confirmed_context
                    ),
                )
                from plc_semantics import (
                    SEMANTICS_SCHEMA_VERSION,
                    strict_semantic_gaps,
                )
                from plc_static_analyzer import STATIC_ANALYSIS_SCHEMA_VERSION
                from plc_timing import TIMING_ANALYSIS_SCHEMA_VERSION

                semantic_gaps = strict_semantic_gaps(program_ir)
                if semantic_gaps:
                    details = "; ".join(
                        f"{item.get('semantic')}({','.join(item.get('devices') or []) or tr('未指定设备')})"
                        for item in semantic_gaps
                    )
                    raise PLCJsonValidationError(
                        tr('扫描周期语义未满足：') + details
                    )
                self._emit("progress", {"stage": "parsed", "message": tr('模型输出解析与硬校验完成')})

                # PLC IR is the canonical source for every persisted/rendered
                # artifact.  Even if a future IR normalizer rewrites legacy
                # ladder details, preview/JSON/CSV/ST will stay in lockstep.
                rendered_ladder = ir_to_ladder(program_ir)
                final_json_str = json.dumps(
                    rendered_ladder, ensure_ascii=False, indent=2
                )
                json_path = self.output_dir / "ladder.json"
                with json_path.open("w", encoding="utf-8") as f:
                    f.write(final_json_str)
                from plc_st_renderer import (
                    ST_RENDERER_SCHEMA_VERSION,
                    render_plc_ir_to_st,
                    validate_st_traceability,
                )

                st_from_ir = render_plc_ir_to_st(program_ir)
                validate_st_traceability(program_ir, st_from_ir)
                st_path = self.output_dir / "program_from_ir.st"
                with st_path.open("w", encoding="utf-8") as f:
                    f.write(st_from_ir)
                ir_path = self.output_dir / "program.ir.json"
                with ir_path.open("w", encoding="utf-8") as f:
                    json.dump(program_ir, f, ensure_ascii=False, indent=2)

                from draw import AdvancedSVGLadder, generate_gx_works2_csv
                drawer = AdvancedSVGLadder()
                svg_content = drawer.generate_ladder(final_json_str)

                output_path = self.output_dir / "ladder.svg"
                with output_path.open("w", encoding="utf-8") as f:
                    f.write(svg_content)

                artifacts = {
                    "json": json_path.name,
                    "ir": ir_path.name,
                    "svg": output_path.name,
                    "st_from_ir": st_path.name,
                }
                if self.plc_model == "FX3U":
                    program_csv = self.output_dir / "program.csv"
                    comment_csv = self.output_dir / "comments.csv"
                    generate_gx_works2_csv(
                        program_ir, str(program_csv), str(comment_csv)
                    )
                    artifacts.update(
                        {
                            "program_csv": program_csv.name,
                            "comment_csv": comment_csv.name,
                        }
                    )
                return ({
                        "target_mode": "ladder",
                        "program_name": self.program_name,
                        "revision": self.revision,
                        "ir_schema_version": IR_SCHEMA_VERSION,
                        "ir_sha256": canonical_sha256(program_ir),
                        "ladder_sha256": program_ir["source"]["ladder_sha256"],
                        "st_from_ir_sha256": hashlib.sha256(
                            st_from_ir.encode("utf-8")
                        ).hexdigest(),
                        "st_renderer_schema_version": ST_RENDERER_SCHEMA_VERSION,
                        "semantic_schema_version": SEMANTICS_SCHEMA_VERSION,
                        "semantic_summary": {
                            "requirements": program_ir["logic"].get("requirements", []),
                            "coverage": program_ir["timing"].get("coverage", []),
                            "state_machine_count": len(
                                program_ir["logic"].get("state_machines", [])
                            ),
                            "regions": [
                                {
                                    "code": region.get("code"),
                                    "kind": region.get("kind"),
                                    "network_count": len(region.get("network_refs", [])),
                                }
                                for region in program_ir["logic"].get("regions", [])
                            ],
                        },
                        "static_analysis_schema_version": STATIC_ANALYSIS_SCHEMA_VERSION,
                        "static_analysis_summary": {
                            "counts": program_ir["analysis"].get("counts", {}),
                            "rules_checked": program_ir["analysis"].get(
                                "rules_checked", []
                            ),
                            "dependency_nodes": len(
                                program_ir["analysis"]
                                .get("dependency_graph", {})
                                .get("nodes", [])
                            ),
                            "dependency_edges": len(
                                program_ir["analysis"]
                                .get("dependency_graph", {})
                                .get("device_edges", [])
                            ),
                        },
                        "timing_analysis_schema_version": TIMING_ANALYSIS_SCHEMA_VERSION,
                        "timing_summary": {
                            "profile": program_ir["timing"]
                            .get("performance", {})
                            .get("profile"),
                            "estimate": program_ir["timing"]
                            .get("performance", {})
                            .get("estimate", {}),
                            "scan_budget": program_ir["timing"]
                            .get("performance", {})
                            .get("scan_budget", {}),
                            "scan_monitor": program_ir["timing"]
                            .get("performance", {})
                            .get("scan_monitor", {}),
                        },
                        "width": int(drawer.width),
                        "height": int(drawer.height),
                        "artifacts": artifacts,
                        "contract_mismatch": (
                            copy.deepcopy(contract_mismatch)
                            if contract_mismatch
                            else None
                        ),
                        "validation": {
                            "status": (
                                "contract_mismatch"
                                if contract_mismatch
                                else "passed"
                            ),
                            "messages": validation_messages
                            or [tr('结构、指令参数和双线圈校验已通过')],
                        },
                    }
                )

            else:
                st_text = parsed_json.get("st_code", "")
                if not st_text:
                    st_text = json_str
                self._emit("progress", {"stage": "parsed", "message": tr('模型输出解析与硬校验完成')})

                output_path = self.output_dir / "program.st"
                with output_path.open("w", encoding="utf-8") as f:
                    f.write(st_text.strip())

                return ({
                        "target_mode": "st",
                        "width": 0,
                        "height": 0,
                        "artifacts": {"st": output_path.name},
                        "validation": {
                            "status": "passed",
                            "messages": [tr('ST 输出结构校验已通过')],
                        },
                    }
                )

        except GenerationError:
            raise
        except Exception as e:
            raise GenerationError(tr('线程运行期异常: {v0}', v0=str(e)))
