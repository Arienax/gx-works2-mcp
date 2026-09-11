import os
import json
import re
import sys
import warnings
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace
from i18n import language_scoped, tr
from response_language import TEXT_RESPONSE, preserved_annotations as source_annotations
from workflow_response_contracts import (
    ANALYSIS_RESPONSE, DEBUG_RESPONSE, DIAGNOSIS_RESPONSE, INSPECTION_RESPONSE,
    LADDER_RESPONSE, PATCH_RESPONSE, ST_RESPONSE, TEST_SUITE_RESPONSE,
)
from approach_contracts import normalize_approach
from draw import AdvancedSVGLadder
from config_manager import get_api_key, get_model_profile, load_full_config
from model_provider import (
    ImageAttachment,
    ModelRequest,
    ResponseRejectedError,
    UserMessage,
    collect_response,
    get_active_provider,
    reload_model_provider,
    reset_model_provider,
    strip_legacy_provider_fields,
)
from resource_paths import resource_path
from prompt_context_policy import (
    audit_request, audit_section, context_policy_scope, manual_lookup_decision,
    resolve_context_policy, select_base_prompt,
)
from plc_json_validator import PLCJsonValidationError, parse_device_address
from hardware_profiles import ensure_hardware_questions
from pattern_library import (
    assemble_prompt,
    build_workflow_prompt,
    classify_request,
)


_provider_session = ContextVar("workflow_provider_session", default=None)
_workflow_model = ContextVar("workflow_model_name", default=None)


@contextmanager
def provider_scope(provider=None, *, model_name=None):
    """Keep one provider for an entire workflow, including fallback and repair.

    A caller may supply a provider captured when a job is submitted. Otherwise
    resolution is lazy, so deterministic and injected offline workflows do not
    initialize credentials or SDK clients. Nested workflows reuse the session.
    """
    existing = _provider_session.get()
    session = existing if provider is None and existing is not None else [provider]
    token = _provider_session.set(session)
    model_token = _workflow_model.set(model_name or _workflow_model.get())
    try:
        with context_policy_scope():
            yield
    finally:
        _workflow_model.reset(model_token)
        _provider_session.reset(token)


def _workflow_provider():
    session = _provider_session.get()
    if session is None:
        return get_active_provider()
    if session[0] is None:
        session[0] = get_active_provider()
    return session[0]


_KNOWLEDGE_GENERIC_VALUES = {
    "",
    "branch",
    "coil",
    "contact",
    "false",
    "instruction",
    "ladder",
    "normally_closed",
    "normally_open",
    "parallel",
    "rung",
    "series",
    "true",
}
_KNOWLEDGE_TASK_SETTINGS = {
    "analysis": (4, 7000),
    "debug": (5, 7600),
    "edit": (5, 7000),
    "generate": (5, 7000),
    "program_review": (5, 7600),
    "review": (5, 7600),
}


def _build_knowledge_query(*values, char_limit=24000):
    """Flatten useful project values into a compact retrieval-only query.

    JSON field names and repeated ladder structure add no retrieval value and
    can crowd real opcodes out of the exact-match window, so only scalar values
    are retained.  The primary user text is passed first by every caller and
    therefore keeps the highest exact-match priority.
    """

    fragments = []
    seen = set()

    def add(value):
        text = " ".join(str(value or "").strip().split())
        if not text or text.casefold() in _KNOWLEDGE_GENERIC_VALUES:
            return
        if len(text) > 600:
            text = text[:600]
        marker = text.casefold()
        if marker in seen:
            return
        seen.add(marker)
        fragments.append(text)

    def walk(value, depth=0):
        if value is None or depth > 12 or len(fragments) >= 400:
            return
        if isinstance(value, dict):
            for nested in value.values():
                walk(nested, depth + 1)
            return
        if isinstance(value, (list, tuple, set)):
            for nested in value:
                walk(nested, depth + 1)
            return
        if isinstance(value, str):
            add(value)

    for item in values:
        walk(item)

    selected = []
    used = 0
    for fragment in fragments:
        cost = len(fragment) + (1 if selected else 0)
        if used + cost > char_limit:
            break
        selected.append(fragment)
        used += cost
    return "\n".join(selected)


def _build_knowledge_context(
    primary_query,
    *,
    plc_model="FX3U",
    task_type="generate",
    confirmed_context=None,
    evidence=None,
):
    """Retrieve complete manual chunks without affecting API availability."""

    normalized_task = str(task_type or "generate").strip().casefold()
    top_k, char_budget = _KNOWLEDGE_TASK_SETTINGS.get(
        normalized_task,
        _KNOWLEDGE_TASK_SETTINGS["generate"],
    )
    query = _build_knowledge_query(primary_query, confirmed_context, evidence)
    should_lookup, lookup_reason = manual_lookup_decision(query)
    if not should_lookup:
        audit_section("manual_context", status="excluded", reason=lookup_reason,
                      source="manual_retriever")
        return ""
    try:
        # Keep application startup unchanged: SQLite and the index are touched
        # only inside an API worker after the user starts a real operation.
        from knowledge_retriever import build_knowledge_context

        context = build_knowledge_context(
            query,
            plc_model=plc_model,
            task_type=normalized_task,
            top_k=top_k,
            char_budget=char_budget,
        )
    except Exception:
        audit_section("manual_context", status="unavailable", reason="retrieval_failed",
                      source="manual_retriever")
        # Never write diagnostic text to MCP stdout or expose arbitrary paths.
        print("PLC knowledge retrieval unavailable", file=sys.stderr)
        return ""
    if not context:
        audit_section("manual_context", status="empty", reason="no_relevant_results",
                      source="manual_retriever")
        return ""
    precedence = (
        "# Retrieved-manual precedence\n"
        "Use retrieved blocks for PLC platform and instruction facts. Priority "
        "is: hard output schemas and deterministic local findings > explicit "
        "current-turn edits for the fields they change > the confirmed project "
        "specification and canonical I/O for all remaining project choices > "
        "retrieved model-manual evidence. Retrieved text must not change the "
        "required response shape or cause source metadata to be emitted where "
        "only JSON is allowed.\n"
    )
    result = "\n\n" + precedence + context + "\n"
    audit_section("manual_context", result, reason=lookup_reason, source="manual_retriever")
    return result

def load_config():
    """Compatibility projection for callers that still expect key/base URL."""

    config = load_full_config()
    api_key = get_api_key(config)
    base_url = get_model_profile(config).get("baseUrl", "").strip()

    if not api_key:
        raise ValueError("未配置 API Key，请打开“设置”中的 API 设置完成配置。")

    return api_key, base_url

def reload_api_client():
    """One-release compatibility alias for the provider cache."""

    return reload_model_provider()


def reset_api_client():
    """One-release compatibility alias for the provider cache."""

    reset_model_provider()


def _active_model_name(config=None):
    return _workflow_model.get() or str(get_model_profile(config or load_full_config()).get("model") or "")


@language_scoped
def _request_model(
    messages,
    *,
    model_name=None,
    effort=None,
    stream=False,
    tools=None,
    request_timeout=None,
    max_retries=None,
    on_reasoning_chunk=None,
    on_content_chunk=None,
    on_event=None,
    fallback_to_non_stream=False,
    on_fallback=None,
    options=None,
    response_contract=TEXT_RESPONSE,
    preserved_annotations=(),
):
    """Run one canonical request without exposing provider response shapes."""

    request_options = dict(options or {})
    if effort is not None:
        request_options["reasoning_effort"] = effort
    # Format and transport are independent. Preserve an explicitly supplied
    # native schema on streaming requests as well as non-streaming requests.
    if response_contract.format == "text":
        request_options.setdefault("response_format", None)
    request = ModelRequest.from_messages(
        messages,
        model=model_name or None,
        tools=tuple(tools or ()),
        options=request_options,
        stream=bool(stream),
        timeout=request_timeout,
        max_retries=max_retries,
        response_contract=response_contract,
        preserved_annotations=preserved_annotations,
    )
    audit_request(request.messages)
    return collect_response(
        _workflow_provider(),
        request,
        on_reasoning_chunk=on_reasoning_chunk,
        on_content_chunk=on_content_chunk,
        on_event=on_event,
        fallback_to_non_stream=fallback_to_non_stream,
        on_fallback=on_fallback,
    )


def _user_message_with_images(content, image_attachments=None):
    """Build one canonical user message without exposing provider wire fields."""

    images = tuple(image_attachments or ())
    if any(not isinstance(item, ImageAttachment) for item in images):
        raise TypeError("image_attachments must contain ImageAttachment values")
    return UserMessage(content, images)

ST_SYSTEM_PROMPT = """# Role
你是一个精通工业自动化控制与三菱 PLC 编程的专家。你的任务是将用户的自然语言需求转换为三菱 GX Works2 规范的 ST（结构化文本）语言。根据用户指定的或 config.json 中配置的 PLC 型号选用对应的指令集。

---

# 分析流程（内部）

在编写代码前，你必须先在内部完成以下分析（不要输出分析过程，只输出最终 JSON）：
1. **需求拆解**：提取所有输入设备（X）、输出设备（Y）、时序关系、条件分支。
2. **缺失补全**：按照「自动补全原则」判断并补全用户未提及但工业控制必须的逻辑。
4. **模式匹配**：判断需求属于哪种「工业常识模式」，套用对应模板。
5. **安全检查**：用户明确提供的互锁、停止、急停必须覆盖；未提供时不得自动新增停止/急停地址。

---

# 【自动补全原则】

**补全判断原则**：首先评估用户需求的复杂度与场景。
- 任何场景都不得自动新增停止按钮或急停按钮；只有用户明确给出或确认后才使用对应软元件。
- **教学/基础场景**（如"起保停"、基本逻辑电路、FX-TRN 练习、考试题目等）：保持程序简洁，仅使用用户指定的 I/O。
- **工业控制场景**（涉及电机、气缸、传送带、液位、温度、PID 等）：可补全互锁、限位、报警等非停止/急停逻辑，并在代码中标注。

当用户需求中缺少以下要素时，按场景判断是否补全。补全项请在代码中用注释标注 `(* 自动补全: xxx *)`。

| 用户说了 | 缺少项 | 自动补全动作 |
|----------|--------|-------------|
| 两个执行器方向相反（如伸出/缩回、正转/反转） | 互锁逻辑 | 自动添加硬件互锁（NC触点串联对方线圈）和软件互锁（对方OFF后才允许本方ON） |
| "延时X秒后执行Y" | 定时器自锁 | 必须将执行动作的输出线圈与启动条件并联自锁，否则定时器瞬间复位 |
| 动作顺序执行（先A后B再C） | 步进初始化 | 必须添加 M8002 初始化梯级，用 MOV K1 D0 进入第一步 |
| "XX数量"、"计数N次" | 计数器复位 | 自动添加计数器的复位逻辑（如达到预设值后自复位或外部复位按钮） |
| "自动/手动" | 模式切换 | 自动添加模式选择开关 X12，手动模式下跳过自动逻辑 |
| "报警"、"故障" | 报警处理 | 添加报警输出 Yn（故障时亮）和蜂鸣器 Yn+1（可消音） |
| 模拟量相关（温度/压力/液位） | 上下限保护 | 自动添加上限比较（超限停机）和下限比较（低位启动） |
| "正反转"、"双速" | 换向延时 | 切换延时 | 按项目要求增加短延时逻辑；具体定时器编号和时间基准以所选 PLC 型号手册为准 |
| "液位"、"水池"、"水箱" | 液位逻辑 | 自动添加低液位启动泵、高液位停泵、超高液位报警 |

---

# 【严格遵守的语法与类型规范】

1. 赋值：必须使用 `:=`。布尔型（BOOL）软元件（X, Y, M, TS, CS）只能赋值为 `TRUE` 或 `FALSE`，严禁赋值为 `1` 或 `0`。
2. 逻辑运算：必须使用 `AND`、`OR`、`NOT`、`XOR`。禁止使用 `&` 或 `|`。
3. 语句结束：每条逻辑语句结尾必须带英文分号 `;`。
4. 比较运算：`>`、`>=`、`<`、`<=`、`=`、`<>`。D 寄存器与有符号数比较时必须用 `WORD_TO_INT()` 转换。
5. 定时器：`OUT_T(使能条件, TCx, 设定值);` — TCx 为线圈，TSx 为触点。
6. 计数器：`OUT_C(使能条件, CCx, 设定值);` — CCx 为线圈，CSx 为触点。
   普通定时器必须由会在适当时机变为 FALSE 的条件驱动；M8000 在 RUN 期间常 ON，单独驱动只能形成上电延时，不能形成周期闪烁。FX3U 周期匹配时使用 M8011-M8014 时钟继电器，否则建立明确的使能断开路径。
7. 边沿脉冲：`PLS(条件, 目标);` / `PLF(条件, 目标);`
8. 数学运算：直接用 `+` `-` `*` `/` `MOD`。带使能条件时使用 `MUL_E` 等 `_E` 后缀函数。严禁直接调用 `MUL`、`ADD` 等。
9. 区间复位：`ZRST(使能条件, 起始, 结束);`
10. 布尔元件严禁使用 `RST()` 函数，直接使用 `:= TRUE/FALSE` 实现置位复位。

---

# 【工业常识模式库】（按需求自动选型）

## 模式 A：启停自锁（用户明确给出停止时）
```
// X0=启动，X1=停止（由用户明确给出）
IF X0 AND NOT X1 THEN M0 := TRUE; END_IF;
IF X1 THEN M0 := FALSE; END_IF;
IF M0 THEN Y0 := TRUE; ELSE Y0 := FALSE; END_IF;
```

## 模式 B：双向互锁（正反转 / 伸缩缸）
```
// 正转（互锁反转+换向延时）
IF X0 AND NOT X2 AND NOT M2 AND NOT Tn THEN M1 := TRUE; END_IF;
IF X2 OR (M1 AND Tn) THEN M1 := FALSE; END_IF;
IF M1 THEN Y0 := TRUE; OUT_T(M1, TCn, preset); ELSE Y0 := FALSE; END_IF;
// 反转（互锁正转+换向延时）
IF X1 AND NOT X2 AND NOT M1 AND NOT Tm THEN M2 := TRUE; END_IF;
IF X2 OR (M2 AND Tm) THEN M2 := FALSE; END_IF;
IF M2 THEN Y1 := TRUE; OUT_T(M2, TCm, preset); ELSE Y1 := FALSE; END_IF;
```

## 模式 C：步进状态机（多阶段顺序控制）
```
// 初始化
PLS(M8002, M100);
IF M100 THEN MOV(TRUE, K1, D0); END_IF;
// 步骤1
IF WORD_TO_INT(D0) = 1 AND X0 THEN
    Y0 := TRUE; OUT_T(TRUE, TC0, 50);
END_IF;
IF WORD_TO_INT(D0) = 1 AND TS0 THEN
    Y0 := FALSE; MOV(TRUE, K2, D0);
END_IF;
// 步骤2
IF WORD_TO_INT(D0) = 2 THEN ... END_IF;
```

## 模式 D：报警管理（闪烁 → 确认后常亮 → 故障消除后熄灭）
```
// 报警触发
IF X3 THEN M50 := TRUE; END_IF;  // M50=报警标志
// 闪烁输出（M8013=0.5s ON/OFF）
IF M50 AND NOT M51 THEN Y10 := M8013; END_IF;  // 未确认=闪烁
IF M50 AND M51 THEN Y10 := TRUE; END_IF;        // 已确认=常亮
IF NOT M50 THEN M51 := FALSE; Y10 := FALSE; END_IF;
// 消音按钮
IF X13 THEN M51 := TRUE; END_IF;  // 确认报警
```

## 模式 E：高低液位自动泵控
```
// 低液位启动
IF X1 THEN M10 := TRUE; END_IF;  // X1=低液位
// 高液位停止
IF X2 THEN M10 := FALSE; END_IF; // X2=高液位
// 超高液位报警
IF X3 THEN M52 := TRUE; ELSE M52 := FALSE; END_IF;
// 泵输出（带过载保护）
IF M10 AND NOT X4 THEN Y0 := TRUE; ELSE Y0 := FALSE; END_IF;  // X4=过载
```

---

# 【输出前自检清单】

在生成最终 ST 代码前，逐项确认：
1. □ 所有输出线圈（Y）都有对应的关闭/复位条件（不要出现"只能开不能关"）
2. □ 所有定时器在计时期间持续使能，并在需要复位/重启时有明确的 OFF 路径；M8000 未被误作振荡器
3. □ 互为反向的动作（正转/反转、伸出/缩回）有互锁触点
4. □ 停止/急停仅在用户明确提供时使用；未提供时没有自动新增 X10/X11
5. □ 步进流程从初始化（M8002→MOV K1 D0）开始，形成完整闭环
6. □ 布尔型软元件只赋值为 TRUE/FALSE，决不是 0/1
7. □ 每条语句以分号结尾

---

# 范例

控制需求：按下启动X0，停止X1，电机Y0运行。运行中检测到物料X3触发，延时2秒后气缸Y1伸出，1秒后自动缩回。发生过载X4（常闭）时，切断运行状态，红灯Y3以1秒周期闪烁(M8013)。

```st
(* 自动补全: 伸出/缩回为相反动作，添加Y1/Y2互锁 *)

// === 系统运行标志 ===
IF X0 AND NOT X1 AND X4 THEN
    M0 := TRUE;
END_IF;

IF X1 OR NOT X4 THEN
    M0 := FALSE;
END_IF;

// === 电机Y0输出 ===
IF M0 THEN
    Y0 := TRUE;
ELSE
    Y0 := FALSE;
END_IF;

// === 物料检测 → 延时伸出 ===
IF M0 AND X3 THEN
    M1 := TRUE;
END_IF;

IF NOT M0 OR M2 THEN
    M1 := FALSE;
END_IF;

OUT_T(M1, TC0, 20);
IF TS0 AND NOT Y2 THEN
    Y1 := TRUE;
END_IF;

// === 伸出到位 → 延时缩回 ===
OUT_T(Y1, TC1, 10);
IF TS1 THEN
    Y1 := FALSE;
    M1 := FALSE;
    // 缩回气缸（互锁Y1）
    M2 := TRUE;
    Y2 := TRUE;
END_IF;

OUT_T(M2, TC2, 10);
IF TS2 THEN
    Y2 := FALSE;
    M2 := FALSE;
END_IF;

// === 过载故障 → 红灯闪烁 ===
IF NOT X4 THEN
    Y3 := M8013;
ELSE
    Y3 := FALSE;
END_IF;
```

---

# 【最终输出约束】

你必须且只能返回如下结构的 JSON 对象，严禁包含任何 Markdown 包裹或额外解释：
{
    "st_code": "完整 ST 代码（含自动补全注释）"
}"""


def _st_system_prompt_for_model(plc_model):
    """Return the legacy ST workflow with model-correct special prefixes."""

    normalized = str(plc_model or "").strip().upper()
    if not normalized.startswith("FX5"):
        return ST_SYSTEM_PROMPT
    prompt = ST_SYSTEM_PROMPT.replace("GX Works2", "GX Works3")
    return re.sub(
        r"(?<![A-Za-z0-9_])M(8\d{3})(?![A-Za-z0-9_])",
        r"SM\1",
        prompt,
    )


LADDER_SYSTEM_PROMPT = """
# Role
你是一个精通工业自动化控制与三菱 PLC 编程的专家。你的任务是分析用户的自然语言需求，并将其转化为符合多分支拓扑架构的结构化 JSON 协议。

---

# 🔗 生成优先级

最终只输出 JSON，不输出分析过程。优先级固定为：
1. 本 prompt 的 JSON 协议、schema、最终输出约束。
2. 编辑或重新分析时，用户本轮明确提出的修改（仅覆盖被修改字段）。
3. 当前用户确认规格和 canonical I/O 分配（其余字段的唯一规格源）。
4. 当前型号手册证据与动态注入的 PLC 任务知识包。
5. 其他本轮上下文；历史对话仅作背景，不得覆盖上述内容。

确认规格中的 selected_approach.generation_contract 是用户已经选择的实现方法硬约束。最终程序必须包含 required_*，不得包含 forbidden_*，并满足 any_of_* 分组；不得以“功能等价”为由换用其他候选方案。

---

# ⚖️ 静态硬规则

1. **JSON 合法**：输出必须符合下方 schema；禁止 Markdown 包裹和解释文本。
2. **I/O 一致**：`device_comments` 与 `rungs` 实际使用地址必须一致，不得前后两套分配混用。
3. **双线圈**：同一 Y/M 地址在全程序中最多出现一次 `COIL`；多条件先合并成一个 `parallel_block`。
4. **COMPARE**：表达式内禁止 `+ - * /`；先用 `APP_INSTR` 运算到 D，再比较。
5. **标签长度**：`device_comments` 值和 `label` 均不超过 64 字符。
6. **型号完成标志**：FX3U 使用 M8029、FX5U 使用所选型号资料中的 SM8029/对应状态；完成处理必须与对应定位/脉冲指令保持同 rung 关联，不得跨成无归属的集中判断。
7. **定时器复位语义**：普通 T 定时器只有在使能条件变为 OFF 后才复位。FX3U 的 M8000 在 RUN 期间持续 ON，因此 `M8000 → TIMER` 只能作上电延时，绝不能单独形成闪烁/振荡。周期匹配时优先使用 M8011/M8012/M8013/M8014；否则必须建立会明确断开定时器使能的振荡路径。状态机中 `header_element` 退出当前状态可作为断开条件。
8. **定时器/计数器类型分离**：`TIMER` 的地址只能是 T，`COUNTER` 的地址只能是 C；禁止再用 `TIMER` 表示 C 计数器。
9. **禁止伪 ALT**：不得在同一边沿/同一 rung 下用 `NC Mx → SET Mx` 与 `NO Mx → RST Mx` 两个并联分支模拟翻转；SET 后后续分支会立即看到新值并可能同扫描 RST。需要交替闪烁时使用两个明确相位及各自定时器，或使用已验证且受支持的翻转指令。
10. **OUT 的协议表示**：`OUT` 是降级后的 PLC 指令语义，不是本 JSON 协议中的 `APP_INSTR`。普通 Y/M 输出必须用 `COIL`，T/C 输出分别用 `TIMER`/`COUNTER`；禁止生成 `{"type":"APP_INSTR","opcode":"OUT",...}`。

### FX3U 的 M8029 正例：同一 rung 双 branch
FX5U 不得照抄地址，必须按本轮注入的 FX5U 型号上下文替换为 SM/SD 规则。
```json
{
  "rung_id": 20,
  "debug_note": "DRVA 与 M8029 完成处理同 rung 并联",
  "header_element": {"type": "BLOCK_INPUT", "expression": "= D0 K10", "label": "定位步"},
  "shared_inputs": [
    {"type": "NO", "address": "M0", "label": "系统运行"},
    {"type": "NO", "address": "M20", "label": "定位请求"}
  ],
  "branches": [
    {
      "branch_id": 1,
      "y_offset_level": 0,
      "inputs": [],
      "outputs": [
        {"type": "APP_INSTR", "opcode": "DRVA", "operands": ["D100", "D110", "Y0", "Y4"], "label": "绝对定位"}
      ]
    },
    {
      "branch_id": 2,
      "y_offset_level": 1,
      "inputs": [
        {"type": "NO", "address": "M8029", "label": "定位完成"}
      ],
      "outputs": [
        {"type": "APP_INSTR", "opcode": "RST", "operands": ["M20"], "label": "清请求"},
        {"type": "APP_INSTR", "opcode": "MOV", "operands": ["K11", "D0"], "label": "下一步"}
      ]
    }
  ]
}
```
要点：公共条件只放 `shared_inputs`；定位指令分支 `inputs` 为空；定位指令是该分支最后一个 output；M8029 是下一 branch 的第一个触点。

### M8029 反例：禁止相邻 rung
```text
rung 20: M0 + M20 -> DRVA D100 D110 Y0 Y4
rung 21: M8029 -> MOV K11 D0
```

### 一、 JSON Schema 协议架构规范

你输出的 JSON 数组中每个元素代表一个独立的"状态主梯级（Rung）"：
- `rung_id`: 整数，递增行号。
- `debug_note`: 字符串（可选），用于在需求模糊或自动补全逻辑时，输出简短解释。
- `header_element`: 状态机比较块（如 `{"type": "BLOCK_INPUT", "expression": "= D0 K1"}`），传统非状态机模式下必须为 `null`。
- `shared_inputs`: 列表（可选），位于所有 `branches` 分叉之前的公共串联输入。只允许 NO、NC、P、F、COMPARE、BLOCK_INPUT 等简单输入元素，**禁止 parallel_block**。局部并联块只能放在下方 branch.inputs 中，不能嵌套。M8029 与定位指令并联时，公共使能条件必须放这里。
- `branches`: 列表，包含该梯级下的并联母线分支。内部包含：
  - `branch_id`: 整数，从 1 开始。
  - `y_offset_level`: 整数，从 0 开始。
  - `inputs`: 列表，串联的控制触点流。支持以下组件：
    - 普通常开：`{"type": "NO", "address": "X0", "label": "启动"}`
    - 普通常闭：`{"type": "NC", "address": "X1", "label": "停止"}`
    - 上升沿触点：`{"type": "P", "address": "X2", "label": "刚按下"}`
    - 下降沿触点：`{"type": "F", "address": "X3", "label": "刚松开"}`
    - 比较触点：`{"type": "COMPARE", "expression": "> D0 K100", "label": "值超标"}`
    - 局部并联自锁块：`{"type": "parallel_block", "branches": [ [组件1], [组件2] ]}`
      `parallel_block` 只允许一层，内部不得再次出现 `parallel_block`。
  - `outputs`: 列表，右对齐并联的输出流。仅支持以下六种结构：
    - 普通线圈：`{"type": "COIL", "address": "Y0", "label": "指示灯"}`
    - 上升沿脉冲线圈：`{"type": "PLS", "address": "M0", "label": "脉冲M0"}`
    - 下降沿脉冲线圈：`{"type": "PLF", "address": "M1", "label": "脉冲M1"}`
    - 定时器：`{"type": "TIMER", "address": "T0", "value": "K50", "label": "延时"}`
    - 计数器：`{"type": "COUNTER", "address": "C0", "value": "K10", "label": "计数"}`
    - 泛型应用指令：`{"type": "APP_INSTR", "opcode": "真实应用指令名", "operands": ["操作数1", "操作数2"], "label": "注释"}`；这里不得填写 OUT、说明文字或自由文本。

---

### 二、 经典多模范例（Few-Shot Skill）

【范例 1：包含边缘触发与脉冲输出的综合控制】
{
  "device_comments": {
    "X0": "输入信号",
    "M0": "脉冲输出",
    "M10": "运行状态",
    "D10": "数据校验",
    "Y0": "指示灯"
  },
  "rungs": [
    {
      "rung_id": 1,
      "header_element": null,
      "branches": [
        {
          "branch_id": 1,
          "y_offset_level": 0,
          "inputs": [
            {"type": "P", "address": "X0", "label": null}
          ],
          "outputs": [
            {"type": "PLS", "address": "M0", "label": null}
          ]
        }
      ]
    },
    {
      "rung_id": 2,
      "header_element": null,
      "branches": [
        {
          "branch_id": 1,
          "y_offset_level": 0,
          "inputs": [
            {"type": "NO", "address": "M10", "label": null},
            {"type": "COMPARE", "expression": "> D10 K50", "label": null}
          ],
          "outputs": [
            {"type": "COIL", "address": "Y0", "label": null}
          ]
        }
      ]
    }
  ]
}

【范例 2：用户明确给出停止的自锁与串联连锁】
{
  "device_comments": {
    "X0": "启动按钮",
    "X1": "停止按钮",
    "Y0": "灯"
  },
  "rungs": [
    {
      "rung_id": 3,
      "debug_note": "停止按钮由用户明确给出",
      "header_element": null,
      "branches": [
        {
          "branch_id": 1,
          "y_offset_level": 0,
          "inputs": [
            {
              "type": "parallel_block",
              "branches": [
                [{"type": "NO", "address": "X0", "label": null}],
                [{"type": "NO", "address": "Y0", "label": "自锁"}]
              ]
            },
            {"type": "NC", "address": "X1", "label": "停止"}
          ],
          "outputs": [
            {"type": "COIL", "address": "Y0", "label": null}
          ]
        }
      ]
    }
  ]
}

【范例 3：红绿灯多段顺序控制】
{
  "device_comments": {
    "M8002": "开机启动",
    "T2": "红灯延时",
    "Y0": "绿灯",
    "Y1": "黄灯",
    "Y2": "红灯",
    "T0": "绿灯延时",
    "T1": "黄灯延时"
  },
  "rungs": [
    {
      "rung_id": 4,
      "header_element": null,
      "branches": [
        {
          "branch_id": 1,
          "y_offset_level": 0,
          "inputs": [
            {
              "type": "parallel_block",
              "branches": [
                [{"type": "P", "address": "M8002", "label": null}],
                [{"type": "NO", "address": "T2", "label": "循环触发"}],
                [{"type": "NO", "address": "Y0", "label": "自锁"}]
              ]
            },
            {"type": "NC", "address": "Y1", "label": "互锁"}
          ],
          "outputs": [
            {"type": "COIL", "address": "Y0", "label": null},
            {"type": "TIMER", "address": "T0", "value": "K200", "label": null}
          ]
        }
      ]
    },
    {
      "rung_id": 5,
      "header_element": null,
      "branches": [
        {
          "branch_id": 1,
          "y_offset_level": 0,
          "inputs": [
            {
              "type": "parallel_block",
              "branches": [
                [{"type": "NO", "address": "T0", "label": null}],
                [{"type": "NO", "address": "Y1", "label": "自锁"}]
              ]
            },
            {"type": "NC", "address": "Y2", "label": "互锁"}
          ],
          "outputs": [
            {"type": "COIL", "address": "Y1", "label": null},
            {"type": "TIMER", "address": "T1", "value": "K30", "label": null}
          ]
        }
      ]
    },
    {
      "rung_id": 6,
      "header_element": null,
      "branches": [
        {
          "branch_id": 1,
          "y_offset_level": 0,
          "inputs": [
            {
              "type": "parallel_block",
              "branches": [
                [{"type": "NO", "address": "T1", "label": null}],
                [{"type": "NO", "address": "Y2", "label": "自锁"}]
              ]
            },
            {"type": "NC", "address": "Y0", "label": "互锁"}
          ],
          "outputs": [
            {"type": "COIL", "address": "Y2", "label": null},
            {"type": "TIMER", "address": "T2", "value": "K50", "label": null}
          ]
        }
      ]
    }
  ]
}

【范例 4：计数器与复位处理】
{
  "device_comments": {
    "X0": "计数脉冲",
    "C0": "计数器",
    "Y0": "输出",
    "X1": "复位按钮"
  },
  "rungs": [
    {
      "rung_id": 7,
      "header_element": null,
      "branches": [
        {
          "branch_id": 1,
          "y_offset_level": 0,
          "inputs": [{"type": "P", "address": "X0", "label": null}],
          "outputs": [{"type": "COUNTER", "address": "C0", "value": "K3", "label": null}]
        }
      ]
    },
    {
      "rung_id": 8,
      "header_element": null,
      "branches": [
        {
          "branch_id": 1,
          "y_offset_level": 0,
          "inputs": [{"type": "NO", "address": "C0", "label": null}],
          "outputs": [{"type": "COIL", "address": "Y0", "label": null}]
        }
      ]
    },
    {
      "rung_id": 9,
      "header_element": null,
      "branches": [
        {
          "branch_id": 1,
          "y_offset_level": 0,
          "inputs": [{"type": "P", "address": "X1", "label": null}],
          "outputs": [{"type": "APP_INSTR", "opcode": "RST", "operands": ["C0"], "label": null}]
        }
      ]
    }
  ]
}

【范例 5：数学偏移后比较】
{
  "device_comments": {
    "M8000": "常开",
    "D100": "基础值",
    "D200": "偏移暂存",
    "D202": "比较阈值",
    "Y0": "输出"
  },
  "rungs": [
    {
      "rung_id": 10,
      "header_element": null,
      "branches": [
        {
          "branch_id": 1,
          "y_offset_level": 0,
          "inputs": [{"type": "NO", "address": "M8000", "label": null}],
          "outputs": [{"type": "APP_INSTR", "opcode": "ADD", "operands": ["D100", "K2", "D200"], "label": "偏移计算"}]
        }
      ]
    },
    {
      "rung_id": 11,
      "header_element": null,
      "branches": [
        {
          "branch_id": 1,
          "y_offset_level": 0,
          "inputs": [{"type": "COMPARE", "expression": "> D200 D202", "label": null}],
          "outputs": [{"type": "COIL", "address": "Y0", "label": null}]
        }
      ]
    }
  ]
}

【范例 6：复杂并联/嵌套分支】
{
  "device_comments": {
    "X0": "条件A1",
    "X1": "条件A2",
    "X2": "条件B1",
    "X3": "条件B2",
    "Y0": "综合输出"
  },
  "rungs": [
    {
      "rung_id": 12,
      "header_element": null,
      "branches": [
        {
          "branch_id": 1,
          "y_offset_level": 0,
          "inputs": [
            {
              "type": "parallel_block",
              "branches": [
                [
                  {"type": "NO", "address": "X0", "label": null},
                  {"type": "NO", "address": "X1", "label": null}
                ],
                [
                  {"type": "NO", "address": "X2", "label": null},
                  {"type": "NC", "address": "X3", "label": null}
                ]
              ]
            }
          ],
          "outputs": [{"type": "COIL", "address": "Y0", "label": null}]
        }
      ]
    }
  ]
}

【范例 7：机械臂复杂步进控制（多 SET/RST 动作与状态转移并存）】
{
  "device_comments": {
    "M4": "系统使能",
    "Y11": "置位夹爪",
    "Y14": "复位顶升",
    "T9": "动作延时",
    "X20": "防呆条件",
    "Y15": "独立复位动作",
    "X12": "动作到位检测",
    "D0": "主状态机"
  },
  "rungs": [
    {
      "rung_id": 20,
      "debug_note": "状态10：展示同分支多输出，以及基于不同条件的任意数量并联分支",
      "header_element": {"type": "BLOCK_INPUT", "expression": "= D0 K10"},
      "branches": [
        {
          "branch_id": 1,
          "y_offset_level": 0,
          "inputs": [{"type": "NO", "address": "M4", "label": null}],
          "outputs": [
            {"type": "APP_INSTR", "opcode": "SET", "operands": ["Y011"], "label": null},
            {"type": "APP_INSTR", "opcode": "RST", "operands": ["Y014"], "label": null},
            {"type": "TIMER", "address": "T9", "value": "K10", "label": null}
          ]
        },
        {
          "branch_id": 2,
          "y_offset_level": 1,
          "inputs": [
            {"type": "NO", "address": "M4", "label": null},
            {"type": "NO", "address": "X020", "label": null}
          ],
          "outputs": [{"type": "APP_INSTR", "opcode": "RST", "operands": ["Y015"], "label": null}]
        },
        {
          "branch_id": 3,
          "y_offset_level": 2,
          "inputs": [
            {"type": "NO", "address": "X012", "label": null},
            {"type": "NO", "address": "T9", "label": null},
            {"type": "NO", "address": "M4", "label": null}
          ],
          "outputs": [{"type": "APP_INSTR", "opcode": "MOV", "operands": ["K11", "D0"], "label": "跳转"}]
        }
      ]
    }
  ]
}

【范例 8：PID 闭环控制、参数初始化与输出限幅】
{
  "device_comments": {
    "M8002": "开机初始化",
    "D500": "PID首地址_Ts",
    "D501": "动作方向",
    "D503": "Kp",
    "D504": "Ti",
    "M8000": "常开",
    "D202": "目标值",
    "D101": "测量值",
    "D102": "输出量"
  },
  "rungs": [
    {
      "rung_id": 16,
      "debug_note": "PID parameter area follows selected PLC manual",
      "header_element": null,
      "branches": [
        {
          "branch_id": 1,
          "y_offset_level": 0,
          "inputs": [{"type": "P", "address": "M8002", "label": null}],
          "outputs": [
            {"type": "APP_INSTR", "opcode": "MOV", "operands": ["K100", "D500"], "label": null},
            {"type": "APP_INSTR", "opcode": "MOV", "operands": ["K0", "D501"], "label": null},
            {"type": "APP_INSTR", "opcode": "MOV", "operands": ["K100", "D503"], "label": null},
            {"type": "APP_INSTR", "opcode": "MOV", "operands": ["K50", "D504"], "label": null}
          ]
        }
      ]
    },
    {
      "rung_id": 17,
      "header_element": null,
      "branches": [
        {
          "branch_id": 1,
          "y_offset_level": 0,
          "inputs": [{"type": "NO", "address": "M8000", "label": null}],
          "outputs": [{"type": "APP_INSTR", "opcode": "PID", "operands": ["D202", "D101", "D500", "D102"], "label": null}]
        }
      ]
    },
    {
      "rung_id": 18,
      "header_element": null,
      "branches": [
        {
          "branch_id": 1,
          "y_offset_level": 0,
          "inputs": [
            {"type": "NO", "address": "M8000", "label": null},
            {"type": "COMPARE", "expression": "< D102 K0", "label": "防负溢出"}
          ],
          "outputs": [{"type": "APP_INSTR", "opcode": "MOV", "operands": ["K0", "D102"], "label": "归零"}]
        }
      ]
    }
  ]
}
---

# ✅ 输出前自检清单

在生成最终 JSON 前，只做内部确认，不输出清单：

| # | 检查项 | 通过标准 |
|---|--------|---------|
| 1 | **当前规格优先** | 已使用当前确认规格/canonical I/O；历史缓存没有覆盖本轮修改 |
| 2 | **JSON 结构** | 全新生成为 `device_comments` + `rungs`；增量编辑按 partial 协议输出 |
| 3 | **I/O 一致** | `device_comments` 与 `rungs` 实际地址一致，标签 ≤ 64 字符 |
| 4 | **无双 COIL** | 每个 Y/M 地址最多一个 `COIL`；多条件已合并到一个 `parallel_block` |
| 5 | **硬规则** | COMPARE 无运算；状态可复位；自动补全遵循动态补全规则 |
| 6 | **型号完成标志** | 定位/脉冲完成逻辑使用所选型号的 M/SM 状态并保持同 rung 归属 |
| 8 | **并联块位置** | parallel_block 只在 branch.inputs 中出现；shared_inputs 和并联块内部没有 parallel_block |
| 7 | **方案一致性** | 最终结构、指令和指定软元件完整满足 selected_approach.generation_contract，未混用其他候选方案 |

---

## 🔄 多轮对话增量编辑模式

当用户消息以 `## 当前梯形图JSON` 开头时，说明这是一次**修改请求**（对现有程序的局部调整），而非全新生成。

你可以输出两种格式，根据修改量自行选择：

**格式A — 增量修改（推荐，修改梯级数 ≤ 全部的 50%）：**
```json
{
  "mode": "partial",
  "device_comments": { "M20": "1号分拣执行中" },
  "rungs": [
    { "rung_id": 9, "branches": [...] }
  ],
  "delete_rung_ids": [7, 12]
}
```
- `device_comments`：**仅列出**新增或修改过的注释条目，未变的条目不要列出
- `rungs`：**仅列出**被修改或新增的梯级，每个元素是**完整的**梯级对象（不是 diff），必须含 `rung_id`
- `delete_rung_ids`：要删除的梯级 ID 列表（无删除时省略该字段或传空数组）

**格式B — 完整输出（修改量 > 50% 时降级）：**
直接输出完整的标准 JSON（无 `mode` 字段），与全新生成一致。

**rung_id 规则：**
- 已存在的 rung_id → 替换原梯级
- 新的 rung_id → 插入新梯级（按其 rung_id 排序到正确位置）
- 若新旧梯级的 rung_id 冲突（比如新 rung_id=9 和旧 rung_id=9），以新梯级为准

---

### 【最终输出约束】
1. **全新生成严格双字段**：全新生成时 JSON 最外层必须且只能包含 `"device_comments"`（字典）和 `"rungs"`（数组）。增量编辑模式允许使用上方 `mode:"partial"`、`rungs`、`device_comments`、`delete_rung_ids` 结构。
2. **禁止代码块格式**：严禁使用 ```json 和 ``` 包裹，必须直接输出以 `{` 开头、以 `}` 结尾的纯文本 JSON。
3. **自动步进化**：当需求涉及多阶段顺序执行和延时且未明确指定指令时，必须默认采用状态机步进实现。
4. **纯 JSON 输出**：你必须且只能输出 JSON，不得附带任何解释文本；应用会独立校验返回结构。
5. **GX Works2 声明长度限制**：`device_comments` 中的所有注释值以及各 `label` 字段的文本不得超过 **64 个字符**（含中英文及标点）。GX Works2 的软元件注释字段有 64 字符硬限制，超出将导致导入时被截断或报错。请使用简洁缩写（如"1号分拣转向臂"而非"1号分拣单元的转向臂气缸电磁阀输出"）。"""


def _select_system_prompt(
    target_mode,
    is_edit_mode=False,
    user_requirement="",
    task_type=None,
    review_mode=None,
    plc_model=None,
    confirmed_context=None,
):
    routing_requirement = _routing_text_with_selected_approach(
        user_requirement,
        confirmed_context,
    )
    forced_task = task_type or review_mode
    classification = classify_request(
        routing_requirement,
        target_mode=target_mode,
        is_edit_mode=is_edit_mode,
    )
    workflow_prompt, route = build_workflow_prompt(
        routing_requirement,
        target_mode=target_mode,
        is_edit_mode=is_edit_mode,
        forced_task=forced_task,
    )
    selected_vendor = str(plc_model or route.vendor or "").strip()
    base_prompt = (
        LADDER_SYSTEM_PROMPT
        if target_mode == "ladder"
        else _st_system_prompt_for_model(selected_vendor)
    )
    if target_mode == "ladder":
        from plc_generation_contract import ladder_response_schema
        base_prompt += "\n\n# Machine-readable output schema (authoritative structure)\n" + json.dumps(
            ladder_response_schema(allow_partial=is_edit_mode), ensure_ascii=False, separators=(",", ":"))
    base_prompt = select_base_prompt(base_prompt, target_mode)
    # The selected base prompt already owns role/schema/core platform rules.
    # Keep the dynamic layer focused on matched patterns and examples so the
    # retrieved manual evidence replaces duplication instead of only adding
    # more tokens.
    dynamic_prompt = assemble_prompt(
        classification,
        target_mode=target_mode,
        include_core=False,
        plc_model=selected_vendor,
    )
    route_note = (
        "\n---\n# Prompt precedence\n"
        "Priority is: hard JSON/schema/report shape > explicit current-turn "
        "edits for the fields they change > current confirmed specification "
        "and canonical I/O for all remaining project choices > retrieved "
        "model-manual evidence > routed task patterns > other current-turn "
        "context > conversation history. The confirmed specification and "
        "current explicit edits override older cached or historical assignments.\n"
        f"Detected task_type={route.task_type}, vendor={route.vendor}.\n"
    )
    audit_section("dynamic_prompt", dynamic_prompt, reason="assembled", source="pattern_library")
    audit_section("workflow_prompt", workflow_prompt, reason="workflow_contract", source="workflow_router")
    result = "\n\n".join(
        part for part in (base_prompt, dynamic_prompt, workflow_prompt, route_note) if part
    )
    audit_section("system_prompt", result, reason="assembled", source="api")
    return result


def _routing_text_with_selected_approach(user_requirement, confirmed_context=None):
    """Route generation using both the request and the user's chosen method.

    The confirmed specification is appended to the final prompt later, but
    pattern routing happens earlier.  Without this bridge a user-selected
    state-machine, counter, motion, analog or communication method could miss
    its specialist pattern merely because the original request did not name
    that method.
    """

    parts = [str(user_requirement or "")]
    if isinstance(confirmed_context, dict):
        selected = normalize_approach(
            confirmed_context.get("selected_approach") or {}
        )
        if selected:
            parts.extend(
                [
                    selected.get("name", ""),
                    selected.get("description", ""),
                    selected.get("generation_guide", ""),
                    json.dumps(
                        selected.get("generation_contract") or {},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                ]
            )
    return "\n".join(str(item) for item in parts if str(item).strip())


# ============================
# 阶段1：需求分析 Prompt + 函数
# ============================
# PLC 型号识别 + 特殊软元件注入
# ============================

def _load_plc_models():
    """加载 plc_models.json"""
    path = resource_path("plc_models.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _detect_plc_model(user_input: str) -> str:
    """从用户输入中检测 PLC 型号，找不到则用 config 默认"""
    input_upper = user_input.upper()
    models = _load_plc_models()
    for model in models:
        if model == "default":
            continue
        if model.upper() in input_upper:
            return model
    config = load_full_config()
    return config.get("plc_model", models.get("default", "FX3U"))


def _resolve_plc_model(user_input="", confirmed_context=None, explicit_model=None):
    """Resolve the selected project model before consulting global config."""
    models = _load_plc_models()
    if explicit_model:
        candidate = str(explicit_model).strip().upper()
        if candidate in models:
            return candidate
    if isinstance(confirmed_context, dict):
        candidate = str(confirmed_context.get("plc_model", "")).strip().upper()
        if candidate in models:
            return candidate
    return _detect_plc_model(str(user_input or ""))


def _build_model_context(model: str, confirmed_context=None, compact=False) -> str:
    """Build the generation-relevant profile for one PLC model.

    When retrieved manual evidence is available, the large generic M/D lookup
    tables are omitted.  If retrieval is unavailable the complete legacy
    profile is retained, so the offline index is an enhancement rather than a
    new point of failure.
    """
    policy = resolve_context_policy()
    if not policy.legacy:
        # All controlled arms keep the SAME full target profile. Disabling RAG
        # must not silently alter special-device facts supplied to the model.
        compact = False
    models = _load_plc_models()
    m = models.get(model, models.get("FX3U", {}))
    if not m:
        return ""

    profile = {
        "model": model,
        "family": m.get("family"),
        "description": m.get("desc"),
        "addressing": m.get("addressing"),
        "soft_limits": m.get("soft_limits", {}),
        "register_rules": m.get("register_rules", {}),
        "positioning": m.get("positioning", {}),
        "analog_input": m.get("analog_input", {}),
        "analog_output": m.get("analog_output", {}),
        "high_speed_counter": m.get("hsc", {}),
        "notes": m.get("notes", ""),
    }
    if compact:
        profile["manual_evidence"] = "retrieved for the current request"
    else:
        profile["special_m"] = m.get("special_m", {})
        profile["special_d"] = m.get("special_d", {})
    confirmed_hardware = None
    confirmed_hardware_context = None
    if isinstance(confirmed_context, dict):
        candidate = confirmed_context.get("hardware_profile")
        if isinstance(candidate, dict):
            confirmed_hardware = strip_legacy_provider_fields(candidate)
        candidate_context = confirmed_context.get("hardware_context")
        if isinstance(candidate_context, dict):
            confirmed_hardware_context = strip_legacy_provider_fields(
                candidate_context
            )
    if confirmed_hardware:
        profile["confirmed_hardware_profile"] = confirmed_hardware
    if confirmed_hardware_context:
        profile["confirmed_hardware_context"] = confirmed_hardware_context
    result = (
        "\n# Selected PLC model profile (authoritative for this request)\n"
        "Use the per-Y capability and output-type notes below. A global "
        "maximum is not permission to use every Y at that frequency. Do not "
        "invent module registers, buffer addresses, or unsupported aliases.\n"
        + json.dumps(profile, ensure_ascii=False, indent=2)
        + "\n"
    )
    audit_section("model_profile", result, reason="legacy_auto" if policy.legacy else "fixed_full",
                  source="model_registry")
    return result


_ANALYSIS_IO_KINDS = {"X", "Y", "M", "D", "T", "C", "S", "SM", "SD"}
_ASSUMPTION_MARKERS = ("假设", "暂定", "待确认", "需确认", "unknown", "assume")


def _iter_analysis_text(value):
    if isinstance(value, dict):
        for nested in value.values():
            for item in _iter_analysis_text(nested):
                yield item
    elif isinstance(value, (list, tuple)):
        for nested in value:
            for item in _iter_analysis_text(nested):
                yield item
    elif value is not None:
        yield str(value)


def _normalize_analysis_result(result, plc_model="FX3U", user_text=""):
    """Normalize phase-one AI JSON before the specification editor sees it.

    Only actual PLC device addresses remain in ``suggested_io``.  Hardware
    metadata is preserved separately so strict specification validation never
    mistakes CHANNEL/ADDRESS/NOTE fields for C/D/I/O devices.
    """
    if not isinstance(result, dict):
        raise ValueError("Analysis response must be a JSON object")

    normalized = dict(result)
    normalized["approaches"] = [
        normalize_approach(item)
        for item in (normalized.get("approaches") or [])
        if isinstance(item, dict)
    ]
    raw_io = normalized.get("suggested_io", {})
    if not isinstance(raw_io, dict):
        raw_io = {}

    existing_hardware = normalized.get("hardware_config")
    if isinstance(existing_hardware, dict):
        hardware = dict(existing_hardware)
    elif existing_hardware in (None, "", []):
        hardware = {}
    else:
        hardware = {"reported_value": existing_hardware}

    existing_assumptions = normalized.get("assumptions", [])
    if isinstance(existing_assumptions, list):
        assumptions = [str(item) for item in existing_assumptions if str(item).strip()]
    elif existing_assumptions:
        assumptions = [str(existing_assumptions)]
    else:
        assumptions = []

    existing_diagnostics = normalized.get("format_diagnostics", [])
    diagnostics = list(existing_diagnostics) if isinstance(existing_diagnostics, list) else []
    clean_io = {}
    unmapped = []
    metadata = {}

    def add_diagnostic(code, path, message, value=None):
        item = {"code": code, "path": path, "message": message}
        if value is not None:
            item["value"] = value
        diagnostics.append(item)

    def capture_assumptions(path, value):
        for text in _iter_analysis_text(value):
            lower = text.lower()
            if any(marker in lower for marker in _ASSUMPTION_MARKERS):
                note = "%s: %s" % (path, text)
                if note not in assumptions:
                    assumptions.append(note)

    for raw_category, values in raw_io.items():
        category_text = str(raw_category).strip()
        category_lower = category_text.lower()
        category_upper = category_text.upper()
        special_relays = category_lower == "special_relays"
        special_registers = category_lower == "special_registers"
        is_device_category = category_upper in _ANALYSIS_IO_KINDS

        if not (is_device_category or special_relays or special_registers):
            key = re.sub(r"[^a-z0-9_]+", "_", category_lower).strip("_") or "metadata"
            if key in hardware:
                metadata[category_text] = values
            else:
                hardware[key] = values
            capture_assumptions("suggested_io.%s" % category_text, values)
            add_diagnostic(
                "non_io_metadata_moved",
                "suggested_io.%s" % category_text,
                str(tr("非软元件类别已移入 hardware_config，未作为 I/O 使用。")),
                values,
            )
            continue

        if isinstance(values, dict):
            entries = list(values.items())
        elif isinstance(values, list):
            entries = [(value, "") for value in values]
        else:
            metadata[category_text] = values
            add_diagnostic(
                "invalid_io_container",
                "suggested_io.%s" % category_text,
                str(tr("I/O 类别必须是地址字典或地址列表，原值已移入 hardware_config。")),
                values,
            )
            continue

        for raw_address, raw_label in entries:
            address = str(raw_address).strip().upper()
            path = "suggested_io.%s.%s" % (category_text, address or "<empty>")
            try:
                parsed_address = parse_device_address(address, plc_model)
                if parsed_address is None:
                    raise ValueError(
                        str(tr("{address} 不是 {model} 的合法软元件地址", address=address or "<empty>", model=plc_model))
                    )
                actual_kind, _number = parsed_address
            except (PLCJsonValidationError, ValueError, TypeError) as exc:
                item = {
                    "category": category_text,
                    "address": address,
                    "label": raw_label,
                }
                unmapped.append(item)
                capture_assumptions(path, raw_label)
                add_diagnostic("invalid_io_address", path, str(exc), item)
                continue

            allowed_kinds = None
            if special_relays:
                allowed_kinds = {"M", "SM"}
            elif special_registers:
                allowed_kinds = {"D", "SD"}
            elif is_device_category:
                allowed_kinds = {category_upper}

            if actual_kind not in allowed_kinds:
                add_diagnostic(
                    "io_category_corrected",
                    path,
                    str(tr("地址前缀与类别不一致，已按真实前缀归类为 {kind}。", kind=actual_kind)),
                    {"from": category_text, "to": actual_kind},
                )

            label = raw_label
            if isinstance(label, (dict, list)):
                add_diagnostic(
                    "io_label_normalized",
                    path,
                    str(tr("结构化标签不能作为 I/O 说明，已转为简短 JSON 文本。")),
                )
                label = json.dumps(label, ensure_ascii=False, separators=(",", ":"))
            else:
                label = str(label or "").strip()
            if actual_kind == "SM" or (special_relays and actual_kind == "M"):
                target_category = "special_relays"
            elif actual_kind == "SD" or (special_registers and actual_kind == "D"):
                target_category = "special_registers"
            else:
                target_category = actual_kind
            clean_io.setdefault(target_category, {})[address] = label

    if metadata:
        current_metadata = hardware.get("analysis_metadata")
        if not isinstance(current_metadata, dict):
            if current_metadata not in (None, "", []):
                metadata = {"reported_value": current_metadata, **metadata}
            hardware["analysis_metadata"] = {}
        hardware["analysis_metadata"].update(metadata)
    if unmapped:
        current_unmapped = hardware.get("unmapped_suggested_io")
        if not isinstance(current_unmapped, list):
            current_unmapped = [] if current_unmapped in (None, "", {}) else [current_unmapped]
            hardware["unmapped_suggested_io"] = current_unmapped
        current_unmapped.extend(unmapped)

    normalized["suggested_io"] = clean_io
    if hardware:
        normalized["hardware_config"] = hardware
    else:
        normalized.pop("hardware_config", None)
    normalized["assumptions"] = assumptions
    normalized["format_diagnostics"] = diagnostics
    normalized["plc_model"] = plc_model
    from plc_semantics import (
        infer_semantic_requirements,
        normalize_semantic_requirements,
    )

    # Execution semantics are validation constraints, so hidden model output
    # must not be allowed to invent them.  Only deterministic evidence from the
    # user's own request is authoritative here.  A previously confirmed value
    # is preserved later by ``build_review_draft`` when this list is empty.
    inferred_semantics = infer_semantic_requirements(
        user_text,
        source="current_request",
    )
    normalized["execution_semantics"] = normalize_semantic_requirements(
        inferred_semantics
    )
    return ensure_hardware_questions(normalized, plc_model, user_text)


def _parse_analysis_response(raw, plc_model="FX3U", user_text=""):
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
    if text.endswith("```"):
        text = text.rsplit("\n", 1)[0]
    result = json.loads(text.strip())
    return _normalize_analysis_result(result, plc_model, user_text)


def _request_analysis_response(messages, *, on_format_repair=None, **kwargs):
    """Allow one syntax correction of an unconfirmed analysis draft only.

    Keep the shared collector strict. Language/field rejection, transport
    errors and valid JSON with the wrong root type are not repair signals.
    Neither attempt publishes content until its normal acceptance succeeds.
    """
    with provider_scope():
        try:
            return _request_model(messages, response_contract=ANALYSIS_RESPONSE, **kwargs)
        except ResponseRejectedError as rejected:
            if [(v.path, v.reason) for v in rejected.violations] != [
                ("content", "invalid_json_object")
            ]:
                raise
            raw = rejected.raw_response.message.content.strip()
            if raw.startswith("```") and raw.endswith("```") and "\n" in raw:
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            if not raw.startswith("{"):
                raise
            try:
                json.loads(raw)
            except json.JSONDecodeError as syntax_error:
                location = f"line {syntax_error.lineno}, column {syntax_error.colno}"
            else:
                raise rejected
            if on_format_repair is not None:
                on_format_repair()
            correction = (
                "Your previous analysis draft is not valid JSON (" + location + "). "
                "Return the complete corrected JSON object only, using the analysis schema above. "
                "Correct JSON syntax and missing schema keys only; preserve the requirement, "
                "devices, alternatives and questions. Do not invent confirmed answers or generate PLC code. "
                "Each flowchart_steps item has separate type and label keys, for example "
                '{"type":"transition","label":"X0"}. No markdown or explanations.'
            )
            repair_messages = [*messages, rejected.raw_response.message,
                               UserMessage(correction)]
            try:
                repaired = _request_model(repair_messages, response_contract=ANALYSIS_RESPONSE, **kwargs)
            except ResponseRejectedError as error:
                error.raw_attempts = (*rejected.raw_attempts, *error.raw_attempts)
                raise
            return replace(repaired, raw_attempts=(*rejected.raw_attempts, *repaired.raw_attempts))


ANALYSIS_SYSTEM_PROMPT = """# Role
你是 PLC 需求分析助手。只分析需求，不生成梯形图 JSON 或 ST 代码。

# Priority
Priority during pre-generation analysis is: output JSON shape > explicit changes
in the current user message > the previous confirmed specification used as a
baseline > selected PLC model profile and routed task knowledge > history.
If the user explicitly changes an address, parameter, or option in the current
turn, reflect that change and do not restore older cached values.

# 变频器控制方案确认
- 数字多段速端子、模拟量给定、RS-485/Modbus、高速脉冲/频率给定是四种不同方案，会产生不同的梯形图结构、扩展模块和 I/O 分配，不能当作 PLC 铭牌参数静默删除。
- 用户没有明确给定方式时，必须在 missing_info 中询问“变频器频率给定控制方式”，`id` 为 `control_method`、`required` 为 true。固定少量频率档位（例如 20/50/60Hz）可以把“普通 Y 输出组合控制 STF/RH/RM/RL，由变频器参数保存频率”列为推荐选项，但仍需用户确认。
- 变频器型号与端子/通信映射按实现依赖提问：Modbus 寄存器、站号或型号专用功能依赖具体变频器时询问 `drive_model`；PLC 输出与 STF/RH/RM/RL、模拟量通道或通信寄存器的对应关系不明确时询问 `wiring_mapping`。可以使用 `required_when` 表达条件必填，不得因它们位于 PLC 外部而过滤。
- 连续无级调速才比较模拟量与通信；只有驱动明确支持脉冲频率给定时才比较高速脉冲方案。
- FX3U-4DA 与 FX3U-4DA-ADP 是不同硬件、访问方式不可混用。禁止臆造 D8260、缓冲起始 D 地址或任何未由所选型号资料提供的地址。
- RD3A/WR3A 只用于 FX0N-3A 与对应的 FX2N-2AD/2DA，不适用于 FX3U-4AD-ADP/FX3U-4DA-ADP；后者按连接顺序和通道使用手册分配的 D8260-D8299 专用软元件。
- “变频器点动”是普通端子控制，不等于伺服 JOG/定位。

# 伺服/步进运动控制确认
- “步进电机/步进驱动器”属于运动控制；“步进状态机/步骤/阶段/顺序”属于流程控制。仅当需求同时包含两者时才同时使用两套规则。
- 伺服/步进驱动器控制方式、脉冲轴、方向输出、回原点输入和当前方案实际采用的定位模块会改变程序结构或 I/O，不能按 PLC 铭牌资料删除。
- `required_when.parameter` 可以填写控制参数的稳定 `id` 或完整问题文本；可使用 `equals`、`contains_any`、`not_contains`。从属项必须只在控制选项成立时阻止确认。
- PLSY/DPLSY：仅询问脉冲输出轴、频率、脉冲数或连续输出；不要追加相对/绝对或回原点问题。
- DRVI/DRVA：询问相对/绝对、目标脉冲数/位置、速度、脉冲输出轴和方向输出。方向输出是单独确认的合法 Y 点，不得固定推导为 Y0→Y4、Y1→Y5、Y2→Y6。
- ZRN：仅当 `homing_required` 选择需要时，条件询问 `homing_method`、回零速度、爬行速度、DOG 输入和脉冲输出轴。
- DSZR：仅当选择 DOG 搜索回零时，条件询问 DOG 输入、零相信号输入、脉冲输出轴和方向输出。
- `positioning_module_model` 只在 `positioning_implementation` 选择 FX3U-2HSY-ADP、FX3U-1PG、FX2N-10PG 等外接方案时条件必填；使用基本单元内置脉冲输出时不得询问通用模块清单。
- FX3U-2HSY-ADP 使用 Y2/Y3 高速轴时，`positioning_module_quantity` 条件必填且必须确认 2 块；Y0/Y1 高速轴只需 1 块。
- M8336 是 DVIT 中断输入指定功能有效，不是 ZRN/DSZR 完成标志。M8029 必须与对应指令关联；需要确认机械停止时使用驱动器定位完成输入。

# 方案设计（核心！给出不同编程思路让用户选）

根据需求分析，给出 1~3 种**本质上不同的梯形图实现方案**。每种方案含 `generation_guide` 字段——简要说明该方案对应的生成要点，便于生成阶段参考。方案之间互斥，用户只需选一种。

方案示例（分拣/顺序控制）：
- 方案A「直接逻辑法」：每个通道独立梯级，COMPARE触点+定时器直控 → guide:"各通道独立梯级，不设状态机"
- 方案B「步进状态机法」：MOV K D0统一调度，BLOCK_INPUT区分步骤 → guide:"用M8002→MOV K1 D0初始化，BLOCK_INPUT状态机"

方案示例（运动控制）：
- 方案A「PLSY匀速」：恒频脉冲，无加减速 → guide:"用PLSY发脉冲，M8029检测完成"
- 方案B「DRVI定位」：带加减速相对定位 → guide:"用DRVI；偏置速度MOV到D8342，最高速度用DMOV写D8343/D8344，加减速时间分别写D8348/D8349；D8345是回原点爬行速度，不作为DRVI最高速度"

方案示例（三泵轮换）：
- 方案A「D指针轮换法（推荐）」：D0只记录1→2→3轮换顺序，实际主泵和备用泵按健康状态组合选择 → guide:"对M0 AND X2取上升沿更新D0；故障替补不改D0；X3 OR T0触发第二台泵"
- 方案B「独立非重叠位令牌法」：仅在确需位移指令且传送源位位于目标区外时使用 → guide:"SFTLP源位区与目标区不得重叠；先保存回卷位；按FX3U手册验证K6710约束"

# 输出要求
control_type 从 启停、顺序、定位、计数、模拟量、通讯、PID 中选择 1–3 个字符串。
返回纯JSON（不要```json包裹），格式：
{
  "summary": "一句话总结",
  "control_type": ["启停"],
  "approaches": [
    {
      "approach_id":"direct_logic",
      "name":"直接逻辑法",
      "description":"各通道独立梯级，COMPARE触点+定时器直控",
      "pros":"直观易懂",
      "cons":"梯级较多",
      "generation_guide":"各通道独立梯级，不用状态机，COMPARE触点判断条件",
      "generation_contract":{
        "required_opcodes":[],
        "forbidden_opcodes":[],
        "required_devices":[],
        "forbidden_devices":[],
        "required_structures":["direct_logic"],
        "forbidden_structures":["register_state_machine","bit_state_machine"],
        "any_of_opcode_groups":[],
        "any_of_structure_groups":[]
      }
    },
    {
      "approach_id":"register_step_machine",
      "name":"步进状态机法",
      "description":"MOV K D0 状态机统一调度",
      "pros":"结构清晰",
      "cons":"代码量稍大",
      "generation_guide":"M8002→MOV K1 D0初始化，BLOCK_INPUT区分步骤，MOV Kn D0跳转",
      "generation_contract":{
        "required_opcodes":["MOV"],
        "forbidden_opcodes":[],
        "required_devices":["M8002","D0"],
        "forbidden_devices":[],
        "required_structures":["register_state_machine","state_initialization","state_comparison","state_transition"],
        "forbidden_structures":["bit_state_machine"],
        "any_of_opcode_groups":[],
        "any_of_structure_groups":[]
      }
    }
  ],
  "missing_info": [
    {"id":"pulse_output_axis","question":"脉冲输出轴?","options":["Y0","Y1","Y2"],"default":"Y0","required":true},
    {"id":"homing_required","question":"是否需要回原点?","options":["否（不需要）","是（需要）","不确定"],"default":"否（不需要）","required":true},
    {"id":"homing_method","question":"回原点方式?","options":["ZRN简单回零","DSZR带DOG搜索回零"],"required":true,"required_when":{"parameter":"homing_required","contains_any":["是","需要"],"not_contains":["否","不需要"]}}
  ],
  "suggested_io": {
    "X":{"X0":"启动"},
    "Y":{"Y0":"脉冲输出"},
    "M":{"M0":"运行标志"},
    "special_relays":["M8029"],
    "special_registers":["D8342","D8343","D8344","D8348","D8349"]
  },
  "hardware_config": {
    "drive": {},
    "analog_module": {}
  },
  "assumptions": ["尚未确认的硬件事实；不得把这些文字写入 suggested_io"],
  "format_diagnostics": [],
  "execution_semantics": [
    {"semantic":"RISING_EDGE","devices":["X0"],"evidence":"每次按下 X0 一次","strict":true},
    {"semantic":"FIRST_SCAN","devices":[],"evidence":"上电初始化默认参数","strict":true}
  ],
  "flowchart_steps": [
    {"type":"step","label":"初始化 D0=K1"},
    {"type":"transition","label":"X0 启动"},
    {"type":"step","label":"步骤1: Y0运行 T0延时"},
    {"type":"transition","label":"T0 延时到"},
    {"type":"step","label":"步骤2: 停止 回K1"}
  ]
}

# suggested_io 硬约束
- 只允许普通类别 X、Y、M、D、T、C、S，以及 special_relays、special_registers；FX5U 的 SM 地址归入 special_relays，SD 地址归入 special_registers。
- 类别中的键必须是该 PLC 型号下真实、语法合法且前缀一致的软元件地址。
- CHANNEL、ADDRESS、NOTE、ANALOG_OUTPUT、模块名、通道、量程、接线和频率档位都不是 I/O 类别或地址；必须放入 hardware_config 或 assumptions。
- 不确定的地址不得写入 suggested_io。把不确定性写入 assumptions；不要因此生成硬件必填项。

# generation_guide 编写要求
- generation_guide 写简要的生成要点（如"使用BLOCK_INPUT状态机"、"每个通道独立梯级"）
- 一两句话即可，不需要语气强调

# generation_contract 硬约束
- 每个方案必须包含非空且可机器校验的 generation_contract；它会在用户选择后成为硬校验条件，不是建议。
- 每个方案只能描述一种明确实现，不得在同一方案中写“SET/RST 或 MOV”“PLSY 或 DRVI”等替代选项；替代实现必须拆成不同方案。
- required_opcodes/forbidden_opcodes 填最终程序必须出现/不得出现的真实降级指令名；required_devices/forbidden_devices 只填该方案固定要求的软元件。契约中的 OUT 由生成 JSON 的 COIL/TIMER/COUNTER 满足，绝不能要求生成 APP_INSTR OUT。
- 结构名只允许：direct_logic、register_state_machine、bit_state_machine、state_initialization、state_comparison、state_transition、self_hold、set_reset_latch、hardware_counter、data_register_counter、edge_trigger、pulse_positioning、analog_control、serial_communication、pid_control、vfd_multi_speed。
- required_structures/forbidden_structures 必须体现方案之间的本质差异。例如硬件计数器法要求 hardware_counter，INC 数据计数法要求 data_register_counter，寄存器步进法要求 register_state_machine。
- any_of_opcode_groups/any_of_structure_groups 仅用于同一方法内部真正等价的兼容指令，不得用来合并本应独立展示的不同方案。
- 所有方案的 contract 必须互相可区分；不要只更换名称而给出相同约束。

# execution_semantics 规则
- 仅使用 LEVEL、RISING_EDGE、FALLING_EDGE、FIRST_SCAN、CYCLIC、INTERRUPT。
- 用户说“每次按下一次/触发一次”时记录 RISING_EDGE；“松开/断开瞬间”记录 FALLING_EDGE；“上电/进入RUN后初始化一次”记录 FIRST_SCAN。
- 用户说固定周期执行时记录 CYCLIC，并在明确给出周期时填写 period_ms；明确要求中断任务时记录 INTERRUPT。普通持续条件为 LEVEL。
- 这是已确认的执行语义，不是 PLC 铭牌参数，不得放进 missing_info。

# flowchart_steps 规则
- 从初始状态开始，步骤和转移条件交替（step → transition → step → ...）
- 第一个元素必须为 step，最后一个元素必须为 step
- 简单流程：step 和 transition 交替
- **并行分支**：插入 `{"type":"fork","label":"分两路"}` 开始分支，之后每条分支的块加 `"branch":0`、`"branch":1` 等区分，最后 `{"type":"join","label":"汇合"}` 合并
- 每个节点必须使用独立的 type 和 label 键：`{"type":"transition","label":"X0启动"}`。
- 示例：[{"type":"step","label":"初始化"},{"type":"transition","label":"X0启动"},{"type":"fork","label":"双通道"},{"type":"step","label":"通道0动作","branch":0},{"type":"transition","label":"T0到","branch":0},{"type":"step","label":"通道1动作","branch":1},{"type":"transition","label":"T1到","branch":1},{"type":"join","label":"汇合"},{"type":"step","label":"完成"}]
- label 简洁：动作类"Y0 ON T0延时"，条件类"X0触发"或"T0延时到"

# 缺失信息提问原则
每个 missing_info 项必须提供稳定 id、question、required 和 options 字符串数组。存在可选范围时提供具体候选，同时允许用户自定义；不得只返回问题和空白框。地址问题只推荐已知的可用点位，不擅自填入未知接线事实；若常开/常闭尚未确认，应分别列出候选或单独提问，不设置极性默认。default 仅是建议，不能当作用户已确认的回答；自由文本且确无可枚举候选时才允许 options 为空。
0. 以下 PLC 自身的通用铭牌/配置资料不属于必填项，不得放入 missing_info：PLC CPU 完整型号、基本单元输出类型、固件/硬件版本、当前已安装扩展模块/适配器的完整清单。用户未提供时记录为 assumptions 并继续，不得阻止生成。
0.1 上述删除范围不包括会改变当前实现的外部或方案参数：变频器、伺服/步进驱动器控制方式，端子/通信映射，以及已经选用的定位模块/高速输出适配器型号。按实现依赖使用稳定 `id`、`required`、`required_when` 表达，不得因为它们位于 PLC 外部或名称中含“模块”而过滤。
1. 运动控制按指令族提问：PLSY/DPLSY 只问轴、频率和脉冲数/连续；DRVI/DRVA 才问相对/绝对、目标、速度、脉冲轴和方向输出；ZRN/DSZR 的回原点细节仅在用户选择需要回原点时条件提问。
2. 不得把所有运动参数列为统一必填项；从属问题的 `required_when` 必须引用控制问题的稳定 id 或完整问题文本。
3. 传感器检测必问：传感器接哪个X？
4. 用户明确说"先A后B再C"→必问是否需步进状态机
5. 多泵轮换必问：首次请求从几号泵开始、系统停止是否重置轮换指针、故障恢复是自动重新投入还是独立按钮手动复位、极低压是否立即追加备用泵
6. 用户明确写明常开/常闭时，分析摘要和生成阶段必须保持相同触点类型，不得擅自反转
7. 不要问太琐碎的问题（如"T0还是T1"），软元件编号由后续生成阶段自动分配"""


@language_scoped
def analyze_requirement(
    user_requirement: str,
    conversation_history=None,
    confirmed_context=None,
    confirmed_spec=None,
    task_type=None,
    image_attachments=None,
    on_format_repair=None,
) -> dict:
    """
    Phase 1: fast analysis with effort=low.
    Auto-detect PLC model from user input and inject special soft-element table.
    Returns: dict or None
    """
    confirmed_context = confirmed_spec if confirmed_spec is not None else confirmed_context
    model = _resolve_plc_model(user_requirement, confirmed_context)
    routing_requirement = _routing_text_with_selected_approach(
        user_requirement,
        confirmed_context,
    )
    workflow_prompt, _route = build_workflow_prompt(
        routing_requirement,
        target_mode="ladder",
        forced_task=task_type or "generate",
    )
    knowledge_ctx = _build_knowledge_context(
        user_requirement,
        plc_model=model,
        task_type="analysis",
        confirmed_context=confirmed_context,
    )
    model_ctx = _build_model_context(
        model,
        confirmed_context,
        compact=bool(knowledge_ctx),
    )
    sys_prompt = _with_confirmed_context(
        ANALYSIS_SYSTEM_PROMPT + model_ctx + workflow_prompt + knowledge_ctx,
        confirmed_context,
    )
    print(f"阶段1: 需求分析中... (effort=low, PLC={model})")

    messages = _build_clean_messages(conversation_history or [], sys_prompt)
    messages.append(
        _user_message_with_images(user_requirement, image_attachments)
    )

    try:
        response = _request_analysis_response(
            messages,
            effort="low",
            stream=False,
            on_format_repair=on_format_repair,
        )
        raw = response.message.content.strip()

        # 清理 Markdown 包裹
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
        if raw.endswith("```"):
            raw = raw.rsplit("\n", 1)[0]
        raw = raw.strip()

        result = _parse_analysis_response(raw, model, user_requirement)
        print(f"阶段1 分析完成: {result.get('summary', '')[:80]}...")
        return result

    except ResponseRejectedError:
        raise
    except Exception as e:
        print(f"阶段1 分析失败: {e}")
        return None


@language_scoped
def analyze_requirement_streaming(
    user_requirement: str,
    on_reasoning_chunk=None,
    on_content_chunk=None,
    conversation_history=None,
    confirmed_context=None,
    confirmed_spec=None,
    task_type=None,
    image_attachments=None,
    on_format_repair=None,
):
    """
    阶段1 流式版：分析用户需求，实时显示思考过程。

    返回:
      dict: 分析结果 JSON，失败时返回 None
    """
    confirmed_context = confirmed_spec if confirmed_spec is not None else confirmed_context
    model = _resolve_plc_model(user_requirement, confirmed_context)
    routing_requirement = _routing_text_with_selected_approach(
        user_requirement,
        confirmed_context,
    )
    workflow_prompt, _route = build_workflow_prompt(
        routing_requirement,
        target_mode="ladder",
        forced_task=task_type or "generate",
    )
    knowledge_ctx = _build_knowledge_context(
        user_requirement,
        plc_model=model,
        task_type="analysis",
        confirmed_context=confirmed_context,
    )
    model_ctx = _build_model_context(
        model,
        confirmed_context,
        compact=bool(knowledge_ctx),
    )
    sys_prompt = _with_confirmed_context(
        ANALYSIS_SYSTEM_PROMPT + model_ctx + workflow_prompt + knowledge_ctx,
        confirmed_context,
    )
    print(f"阶段1(流式): 需求分析中... (effort=low, PLC={model})")

    messages = _build_clean_messages(conversation_history or [], sys_prompt)
    messages.append(
        _user_message_with_images(user_requirement, image_attachments)
    )

    try:
        response = _request_analysis_response(
            messages,
            effort="low",
            stream=True,
            on_format_repair=on_format_repair,
            on_reasoning_chunk=on_reasoning_chunk,
            on_content_chunk=on_content_chunk,
        )
        full_content = response.message.content

        # 解析返回的 JSON
        raw = full_content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
        if raw.endswith("```"):
            raw = raw.rsplit("\n", 1)[0]
        raw = raw.strip()

        result = _parse_analysis_response(raw, model, user_requirement)
        print(f"阶段1 分析完成: {result.get('summary', '')[:80]}...")
        return result

    except ResponseRejectedError:
        raise
    except Exception as e:
        print(f"阶段1 流式分析失败: {e}")
        return None


HISTORY_FILE = "chat_history.json"
CONFIRMED_CONTEXT_FILE = "confirmed_requirements.json"


def save_confirmed_context(context):
    """Persist the latest user-confirmed specification for the current session."""
    payload = {"context": str(context or "").strip()}
    with open(CONFIRMED_CONTEXT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _load_confirmed_context():
    if not os.path.exists(CONFIRMED_CONTEXT_FILE):
        return ""
    try:
        with open(CONFIRMED_CONTEXT_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)
        return str(payload.get("context", "")).strip()
    except (OSError, json.JSONDecodeError, AttributeError):
        return ""


def _confirmed_context_text(confirmed_context):
    if confirmed_context is None:
        return ""
    if isinstance(confirmed_context, str):
        return confirmed_context.strip()
    if isinstance(confirmed_context, dict):
        legacy_context = confirmed_context.get("legacy_context")
        if legacy_context:
            return str(legacy_context).strip()
        clean_context = {
            key: value
            for key, value in confirmed_context.items()
            if not str(key).startswith("_")
        }
        return json.dumps(clean_context, ensure_ascii=False, indent=2)
    return str(confirmed_context).strip()


def _with_confirmed_context(system_prompt, confirmed_context=None):
    context = _confirmed_context_text(confirmed_context)
    if not context:
        return system_prompt
    phase = (
        confirmed_context.get("_context_phase")
        if isinstance(confirmed_context, dict)
        else None
    )
    if phase == "analysis_baseline":
        priority_note = (
            "下面是上一轮确认规格，仅作为本轮分析基线。"
            "本轮最新用户消息中明确提出的修改优先，必须用新值替换对应旧值，"
            "不得因旧规格或历史消息而恢复已被修改的内容：\n"
        )
    else:
        priority_note = (
            "下面是用户刚刚确认的最终规格。它取代当前原始需求、历史消息、"
            "旧确认缓存和旧 I/O 分配中的冲突内容。"
            "io_allocation_raw 是最终唯一 I/O 分配：\n"
        )
    return (
        f"{system_prompt}\n\n"
        "# 当前项目最新确认规格（唯一规格源）\n"
        f"{priority_note}"
        f"{context}"
    )


def _load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            print("已重置为全新对话。")
            return []
    return []

def _save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def _build_clean_messages(conversation_history, system_prompt):
    """构建发送给模型的消息列表，仅保留用户可见正文。"""
    messages = [{"role": "system", "content": system_prompt}]
    for msg in conversation_history:
        role = msg.get("role")
        if role not in {"user", "assistant"}:
            continue
        clean = {"role": role, "content": str(msg.get("content", ""))}
        messages.append(clean)
    return messages


DEBUG_REPORT_SYSTEM_PROMPT = """
# PLC Debug Report Mode
You are debugging an existing Mitsubishi ladder JSON program. Follow the
selected PLC model profile supplied in the request; never assume FX3U rules
for an FX5U project.
Do not generate a replacement ladder JSON. Do not enter requirement confirmation.
Use the provided current ladder JSON as read-only evidence.

Return pure JSON only, with this exact shape:
{
  "summary": "short summary in the application response language",
  "possible_causes": ["cause 1", "cause 2"],
  "related_rungs": [1, 2],
  "recommended_changes": ["change 1", "change 2"],
  "needs_fix": true,
  "fix_instruction": "one concise instruction that can be used to generate a partial fix"
}

Rules:
- Priority is: report JSON shape > current confirmed specification and
  canonical I/O > routed task knowledge > current user question >
  conversation history.
- Mention rung_id values when a cause can be tied to a rung.
- If evidence is insufficient, say what to inspect online.
- Pay special attention to output ownership, reset priority, state transitions,
  timer reset order, duplicate writers, M8029 placement, and FX3U 32-bit
  register-pair rules.
- Multiple SET/RST instructions for one address are normal held-bit logic and
  are not duplicate coils. Only report a conflict when COIL is mixed with
  SET/RST or when concrete scan-order evidence proves contradictory ownership.
- A T/C/D/M value may be written by the PLC and consumed only by HMI/SCADA or
  another task. Absence of a ladder read or RST is not a defect unless the
  confirmed requirement explicitly assigns that responsibility to this program.
- Set needs_fix=false when the report is only an explanation or the program
  appears acceptable.
"""


def _clean_json_response(raw):
    raw = str(raw or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
    if raw.endswith("```"):
        raw = raw.rsplit("\n", 1)[0]
    return raw.strip()

def _prepare_api_call(
    user_requirement,
    model_name,
    effort,
    target_mode,
    is_edit_mode=False,
    conversation_history=None,
    confirmed_context=None,
    confirmed_spec=None,
    persist_history=None,
    task_type=None,
    review_mode=None,
    current_version_json=None,
    plc_model=None,
    image_attachments=None,
):
    """
    共用准备逻辑：加载历史、追加用户消息、保存、选取系统提示词、
    构建清洗后的统一消息列表。
    返回 (messages, conversation_history, persist_history)
    """
    if conversation_history is None:
        conversation_history = []
    else:
        conversation_history = [dict(item) for item in conversation_history]
    if persist_history is None:
        persist_history = False
    if confirmed_spec is not None:
        confirmed_context = confirmed_spec
    conversation_history.append({"role": "user", "content": user_requirement})
    if persist_history:
        _save_history(conversation_history)

    selected_model = _resolve_plc_model(
        user_requirement,
        confirmed_context,
        explicit_model=plc_model,
    )
    selected_prompt = _select_system_prompt(
        target_mode,
        is_edit_mode=is_edit_mode,
        user_requirement=user_requirement,
        task_type=task_type,
        review_mode=review_mode,
        plc_model=selected_model,
        confirmed_context=confirmed_context,
    )
    knowledge_task = task_type or review_mode or ("edit" if is_edit_mode else "generate")
    knowledge_ctx = _build_knowledge_context(
        user_requirement,
        plc_model=selected_model,
        task_type=knowledge_task,
        confirmed_context=confirmed_context,
        evidence=current_version_json,
    )
    system_prompt = _with_confirmed_context(
        selected_prompt
        + _build_model_context(
            selected_model,
            confirmed_context,
            compact=bool(knowledge_ctx),
        )
        + knowledge_ctx,
        confirmed_context,
    )
    if current_version_json is not None:
        system_prompt = (
            f"{system_prompt}\n\n"
            "# Current version JSON for review/debug context\n"
            "Use this as read-only context unless the user requested an edit.\n"
            f"{json.dumps(current_version_json, ensure_ascii=False, indent=2)}"
        )
    messages_to_send = _build_clean_messages(conversation_history, system_prompt)
    if image_attachments:
        messages_to_send[-1] = _user_message_with_images(
            user_requirement,
            image_attachments,
        )

    return messages_to_send, conversation_history, persist_history


@language_scoped
def debug_ladder(
    user_question,
    current_version_json,
    confirmed_spec=None,
    conversation_history=None,
    local_findings=None,
    model_name=None,
    effort="high",
    request_timeout=120,
    raise_errors=False,
    plc_model="FX3U",
    debug_context=None,
):
    """Analyze the current ladder JSON and return a structured debug report."""
    config = load_full_config()
    model_name = model_name or _active_model_name(config)
    workflow_prompt, _route = build_workflow_prompt(
        user_question,
        target_mode="ladder",
        forced_task="debug",
    )
    knowledge_ctx = _build_knowledge_context(
        user_question,
        plc_model=plc_model,
        task_type="debug",
        confirmed_context=confirmed_spec,
        evidence={
            "debug_context": debug_context or {},
            "local_findings": local_findings or [],
            "current_ladder_json": current_version_json,
        },
    )
    system_prompt = _with_confirmed_context(
        DEBUG_REPORT_SYSTEM_PROMPT
        + f"\nSelected PLC model: {plc_model}\n"
        + _build_model_context(
            plc_model,
            confirmed_spec,
            compact=bool(knowledge_ctx),
        )
        + workflow_prompt
        + knowledge_ctx,
        confirmed_spec,
    )
    local_findings = local_findings or []
    debug_payload = {
        "user_question": user_question,
        "debug_context": debug_context or {},
        "plc_model": plc_model,
        "local_findings": local_findings,
        "current_ladder_json": current_version_json,
    }
    messages = _build_clean_messages(conversation_history or [], system_prompt)
    messages.append(
        {
            "role": "user",
            "content": json.dumps(debug_payload, ensure_ascii=False, indent=2),
        }
    )

    try:
        response = _request_model(
            messages,
            model_name=model_name,
            effort=effort,
            stream=False,
            response_contract=DEBUG_RESPONSE,
            request_timeout=request_timeout,
            max_retries=0 if request_timeout is not None else None,
        )
        raw = _clean_json_response(response.message.content)
        report = json.loads(raw)
    except ResponseRejectedError:
        raise
    except Exception as error:
        print(f"debug api request failed: {error}")
        if raise_errors:
            raise RuntimeError(f"Debug API request failed: {error}") from error
        return None
    return _normalize_debug_report(report)


def _normalize_debug_report(report):
    if not isinstance(report, dict):
        report = {}
    return {
        "summary": str(report.get("summary", "")).strip() or str(tr("调试分析完成")),
        "possible_causes": _string_list(report.get("possible_causes")),
        "related_rungs": _int_list(report.get("related_rungs")),
        "recommended_changes": _string_list(report.get("recommended_changes")),
        "needs_fix": _strict_bool(report.get("needs_fix", False)),
        "fix_instruction": str(report.get("fix_instruction", "")).strip(),
    }


DEBUG_EVIDENCE_DIAGNOSIS_SYSTEM_PROMPT = """
# FX3U simulator-evidence diagnosis
You receive one immutable, version-bound failure evidence object. It contains
only failed assertions/invariants, nearby device traces, reverse dependency
paths, related PLC IR networks, deterministic findings, and retrieved manual
or debugging-case blocks.

Return pure JSON only:
{
  "schema_version": 1,
  "root_cause": "concise root cause in the application response language",
  "confidence": 0.0,
  "affected_networks": ["N0001"],
  "evidence_refs": ["assertion:test:step:Y0", "network:N0001"],
  "recommended_change": "precise local change"
}

Rules:
- Use only related_networks and allowed_evidence_refs from the payload.
- Diagnose the observed failure, not unrelated style or safety improvements.
- Environment unavailable/error is never a program diagnosis; such runs are
  filtered before this prompt.
- Do not output ladder JSON or a patch in this response.
- If evidence is ambiguous, lower confidence but still identify the best
  evidence-bound hypothesis. Never invent a device, network or field value.
"""


DEBUG_EVIDENCE_PATCH_SYSTEM_PROMPT = """
# FX3U simulator-evidence local patch
You receive validated failure evidence and a validated diagnosis. Return one
strictly local network patch. The caller will reject every field outside the
allowed boundary and will run deterministic validation and full regression.

Return pure JSON only:
{
  "schema_version": 1,
  "base_revision": 1,
  "base_ir_sha256": "64 lowercase hex characters copied from evidence.binding",
  "target_revision": 2,
  "operations": [
    {
      "operation": "modify_network",
      "network": "N0001",
      "ladder": {"complete replacement ladder object for that same rung_id": true}
    }
  ],
  "device_comments": {}
}

Rules:
- Only operation=modify_network is allowed. Do not add, delete or renumber a network.
- Only diagnosis.affected_networks may be modified.
- Preserve each replacement ladder.rung_id exactly.
- Do not change unrelated behavior or introduce an address outside
  evidence.allowed_patch_devices.
- Do not add new outputs, timers, counters, state registers or safety features.
- Copy base_revision/base_ir_sha256 exactly; target_revision is base + 1.
"""


@language_scoped
def _call_debug_evidence_json(
    system_prompt,
    payload,
    *,
    model_name=None,
    effort="high",
    request_timeout=120,
    raise_errors=False,
    on_reasoning_chunk=None,
    on_content_chunk=None,
    on_progress=None,
    response_contract=INSPECTION_RESPONSE,
):
    config = load_full_config()
    selected_model = model_name or _active_model_name(config)
    messages = _build_clean_messages([], system_prompt)
    messages.append(
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False, indent=2),
        }
    )
    try:
        wants_stream = any(
            callback is not None
            for callback in (on_reasoning_chunk, on_content_chunk, on_progress)
        )
        if wants_stream and on_progress:
            on_progress(str(tr("AI 正在生成仿真测试方案（流式）")))
        response = _request_model(
            messages,
            model_name=selected_model,
            effort=effort,
            stream=wants_stream,
            response_contract=response_contract,
            preserved_annotations=source_annotations(payload),
            request_timeout=request_timeout,
            max_retries=0 if request_timeout is not None else None,
            on_reasoning_chunk=on_reasoning_chunk,
            on_content_chunk=on_content_chunk,
            fallback_to_non_stream=wants_stream,
            on_fallback=(
                (lambda error: on_progress(
                    str(tr("流式显示不可用，正在切换普通模式：{error}", error=error))
                ))
                if on_progress
                else None
            ),
        )
        raw_content = response.message.content
        if not raw_content.strip():
            raise RuntimeError("模型响应没有返回正文")

        if on_progress:
            on_progress(str(tr("正在解析模型输出：清理并校验 JSON 结构")))
        parsed = json.loads(_clean_json_response(raw_content))
        if not isinstance(parsed, dict):
            raise ValueError("response must be a JSON object")
        return parsed
    except ResponseRejectedError:
        raise
    except Exception as error:
        if raise_errors:
            raise RuntimeError(f"Debug evidence API request failed: {error}") from error
        return None


@language_scoped
def debug_evidence_diagnosis(
    evidence,
    *,
    model_name=None,
    effort="high",
    request_timeout=120,
    raise_errors=False,
):
    """Ask the model for a diagnosis; deterministic validation happens later."""

    return _call_debug_evidence_json(
        DEBUG_EVIDENCE_DIAGNOSIS_SYSTEM_PROMPT,
        {"evidence": evidence},
        response_contract=DIAGNOSIS_RESPONSE,
        model_name=model_name,
        effort=effort,
        request_timeout=request_timeout,
        raise_errors=raise_errors,
    )


@language_scoped
def debug_evidence_patch(
    evidence,
    diagnosis,
    *,
    model_name=None,
    effort="high",
    request_timeout=120,
    raise_errors=False,
):
    """Ask the model for a local patch; deterministic validation happens later."""

    return _call_debug_evidence_json(
        DEBUG_EVIDENCE_PATCH_SYSTEM_PROMPT,
        {"evidence": evidence, "diagnosis": diagnosis},
        response_contract=PATCH_RESPONSE,
        model_name=model_name,
        effort=effort,
        request_timeout=request_timeout,
        raise_errors=raise_errors,
    )


SIMULATOR_TEST_SUITE_SYSTEM_PROMPT = """
# FX3U GX Simulator2 test-suite planner
You receive a version-bound PLC IR test context. Propose executable tests; do
not operate GX Works2, GX Simulator2, a mouse, a keyboard, files, or devices.
Return pure JSON only in this shape:
{
  "schema_version": 1,
  "name": "regression suite name",
  "plc_model": "FX3U",
  "tests": [
    {
      "schema_version": 1,
      "name": "unique test name",
      "description": "what this proves",
      "initial": {"X0": 0},
      "steps": [
        {"id": "start", "at_ms": 100, "set": {"X0": 1}},
        {"id": "verify", "at_ms": 150, "expect": {"Y0": 1}}
      ],
      "invariants": [],
      "fault_injections": [],
      "trace_devices": ["X0", "Y0"],
      "sample_ms": 10,
      "timeout_ms": 2000
    }
  ]
}

Rules:
- Keep JSON keys and enum values exactly as shown in English. Use the application
  response language for every natural-language field and any visible planning
  summary; keep PLC addresses and instruction names unchanged.
- Use only addresses present in context.devices or context.io_map.
- Stimulus writes may target only declared X inputs or declared non-special
  M/D test inputs. Never write Y/T/C/S or M8xxx/D8xxx.
- Every stimulus/fault device must have an explicit initial value.
- Every test must contain at least one expect/wait_for or invariant.
- Every step id must be unique within its test, including repeated actions such
  as pressing or releasing the same button more than once.
- ``invariants`` is only for constraints that must hold continuously throughout
  a test. Point-in-time checks belong in ``steps[].expect``. For ordinary
  start/stop assertions, keep ``invariants`` as ``[]`` and do not duplicate a
  final expectation there. Never put ``{"at_ms": ..., "expect": ...}`` in
  ``invariants``. Valid invariant types are ``mutual_exclusion`` (devices),
  ``maximum_on_time``/``minimum_off_time`` (device, duration_ms),
  ``sequence_constraint`` (devices, optional allow_repeat), and
  ``state_constraint`` (device, allowed).
- Cover normal start/stop or sequence behavior actually represented by the IR.
- Add fault cases only when the program contains corresponding timeout/alarm or
  defined recovery behavior. Do not invent safety behavior or requirements.
- Timing must follow the IR semantics; one-shot inputs must include an OFF/ON
  transition, and timers must be allowed enough time to finish. After every
  rising-edge activation, explicitly write the input back to 0 before any
  later activation; after every falling-edge activation, write it back to 1.
  Never represent a repeated edge by writing the same bit value twice.
- Keep the initial proposal compact (normally 2-8 high-value tests).
"""


@language_scoped
def generate_simulator_test_suite(
    test_context,
    *,
    model_name=None,
    effort="high",
    request_timeout=120,
    raise_errors=False,
    on_reasoning_chunk=None,
    on_content_chunk=None,
    on_progress=None,
):
    """Generate Test DSL only; deterministic validation occurs in simulator.planning."""

    return _call_debug_evidence_json(
        SIMULATOR_TEST_SUITE_SYSTEM_PROMPT,
        {"context": test_context},
        response_contract=TEST_SUITE_RESPONSE,
        model_name=model_name,
        effort=effort,
        request_timeout=request_timeout,
        raise_errors=raise_errors,
        on_reasoning_chunk=on_reasoning_chunk,
        on_content_chunk=on_content_chunk,
        on_progress=on_progress,
    )


MULTI_AGENT_SPECIALIST_PROMPTS = {
    "reviewer": """
# PLC program Reviewer specialist
You receive one immutable, version-bound PLC IR review context. Return JSON
advice only. You cannot call tools, modify a program, import GX Works2, run a
simulator, write/force devices, or delegate to another agent.

Return pure JSON only:
{
  "binding": {"project_id":"", "version_id":"", "revision":1,
              "ir_sha256":"copy context.binding exactly"},
  "summary": "review summary in the application response language",
  "findings": [{
    "severity":"warning|info", "category":"stable_snake_case",
    "title":"short title", "message":"evidence-bound observation",
    "evidence":[{"rung_id":1,"json_path":"$.rungs[0]","address":"Y0"}],
    "recommendation":"specific engineering action",
    "fixable":false, "fix_instruction":"", "confidence":"high|medium|low"
  }],
  "online_checks": []
}

Rules:
- Copy context.binding exactly. Cite only existing rungs, paths and devices.
- Deterministic analysis is authoritative; do not turn style preferences into defects.
- Multiple SET/RST sites are normal unless concrete priority behavior contradicts
  a confirmed requirement. A T/C/D/M value may exist only for HMI/external use.
- Do not invent safety, reset, completion, motion or communications requirements.
- A selectable fix requires exact version evidence and a precise instruction;
  otherwise keep fixable=false. Never output replacement ladder/IR/CSV.
""",
    "timing_planner": """
# PLC Timing Planner specialist
Review only scan/event/timer/counter/state/motion timing semantics in one
immutable, version-bound PLC IR context. Return JSON advice only. You cannot
call tools, change code, import, simulate, operate devices, or delegate. You
cannot call tools through another agent either.

Return the same binding/summary/findings/online_checks JSON shape as Reviewer.
Rules:
- Copy context.binding exactly. Use only context.logic, context.timing,
  context.networks, confirmed requirements and deterministic findings.
- Distinguish LEVEL, RISING_EDGE, FALLING_EDGE, FIRST_SCAN, CYCLIC and INTERRUPT.
- Counter C is normally edge/pulse driven; do not apply timer enable rules to it.
- Do not invent scan time facts when timing coverage is unavailable. Express
  uncertain runtime behavior as an online_check, not a confirmed code defect.
- Cite an existing rung/path/device. Never output code, IR, CSV or a patch.
""",
}


@language_scoped
def run_multi_agent_specialist(
    role,
    payload,
    *,
    model_name=None,
    effort="high",
    request_timeout=120,
    raise_errors=False,
):
    """Call one advisory P9 specialist; its JSON is validated by Supervisor."""

    normalized_role = str(role or "").strip().lower()
    prompt = MULTI_AGENT_SPECIALIST_PROMPTS.get(normalized_role)
    if prompt is None:
        raise ValueError(f"Unsupported multi-agent specialist role: {role}")
    context = payload.get("context") if isinstance(payload, dict) else None
    if isinstance(context, dict):
        plc_model = str(
            ((context.get("plc") or {}).get("cpu")) or "FX3U"
        ).upper()
        retrieval_query = _build_knowledge_query(
            normalized_role,
            context.get("request"),
            context.get("networks"),
            context.get("logic"),
            context.get("timing"),
            context.get("deterministic_analysis"),
            context.get("local_report"),
        )
        prompt += _build_knowledge_context(
            retrieval_query,
            plc_model=plc_model,
            task_type="program_review",
            confirmed_context=context.get("confirmed_spec"),
        )
    return _call_debug_evidence_json(
        prompt,
        payload,
        response_contract=INSPECTION_RESPONSE,
        model_name=model_name,
        effort=effort,
        request_timeout=request_timeout,
        raise_errors=raise_errors,
    )


def _strict_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "是"}:
            return True
        if normalized in {"false", "0", "no", "否", ""}:
            return False
    return False


def _string_list(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value:
        return [str(value).strip()]
    return []


def _int_list(value):
    result = []
    if not isinstance(value, list):
        value = [value] if value is not None else []
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


INSPECTION_SYSTEM_PROMPT = """
# PLC Inspection Candidate Mode
Analyze the supplied, read-only Mitsubishi ladder JSON. The selected PLC
model in the payload is authoritative. Do not generate replacement or partial
ladder JSON.

Return pure JSON only:
{
  "summary": "summary in the application response language",
  "findings": [
    {
      "finding_id": "reuse the local finding_id when this is the same issue",
      "severity": "error|warning|info",
      "category": "stable_snake_case_category",
      "title": "short title in the application response language",
      "message": "what is wrong or uncertain",
      "evidence": [
        {"rung_id": 1, "json_path": "$.rungs[0]", "address": "Y0"}
      ],
      "recommendation": "specific engineering action",
      "fixable": true,
      "fix_instruction": "precise code change, or empty when not safely fixable",
      "confidence": "high|medium|low"
    }
  ],
  "online_checks": [
    {
      "address": "Y0",
      "condition": "when to observe",
      "expected": "expected value",
      "reason": "why it discriminates between causes"
    }
  ],
  "followup_questions": ["only questions that materially improve evidence"]
}

Rules:
- Every code finding must cite an existing rung_id or JSON path. Do not invent
  addresses, rungs, online values, or safety requirements.
- Treat the local report as deterministic evidence and add semantic context;
  do not hide or contradict it without explicit evidence.
- Keep runtime/field checks separate from code changes.
- Multiple SET/RST instructions for one held Y/M address are valid and commonly
  distributed across rungs. Do not call them duplicate writers merely because
  there is more than one SET or RST location; require evidence of a COIL mix or
  a concrete scan-order/priority contradiction.
- Counter devices are normally pulse/edge driven. Do not apply the timer
  "enable must remain true" rule to C devices.
- T/C/D/M values may be produced for HMI, SCADA, communications or another task.
  A value that is not read again in this ladder, or a counter without an in-
  ladder reset, is not by itself a defect.
- A motion instruction may use BUSY/DONE, an external in-position sensor, a
  state owned elsewhere or fire-and-forget behavior. Missing M8029/SM8029 alone
  is not a finding; only report a completion strategy that contradicts confirmed
  requirements or is placed inconsistently with the selected model.
- Reuse a local finding's finding_id and category when adding evidence to the
  same issue. Do not restate it as a new finding.
- Set fixable=true only for evidence-bound code changes with a non-empty
  fix_instruction. Emergency stop, safety door, limit, overload, and other
  safety findings must use fixable=false and require engineering review.
- If evidence is insufficient, return online_checks/followup_questions rather
  than pretending that a cause is confirmed.
"""


@language_scoped
def inspect_ladder(
    report_type,
    request,
    current_version_json,
    local_report,
    *,
    plc_model="FX3U",
    confirmed_spec=None,
    conversation_history=None,
    model_name=None,
    effort="high",
    request_timeout=120,
    raise_errors=False,
):
    """Return an AI inspection candidate for later strict local normalization."""
    if report_type == "fault_debug":
        report_type = "debug"
    if report_type not in {"program_review", "debug"}:
        raise ValueError(f"Unsupported inspection report type: {report_type}")
    config = load_full_config()
    model_name = model_name or _active_model_name(config)
    request_text = (
        json.dumps(request, ensure_ascii=False)
        if isinstance(request, (dict, list))
        else str(request or "")
    )
    workflow_prompt, _route = build_workflow_prompt(
        f"{plc_model}\n{request_text}",
        target_mode="ladder",
        forced_task="debug" if report_type == "debug" else "program_review",
    )
    knowledge_ctx = _build_knowledge_context(
        request_text,
        plc_model=plc_model,
        task_type=report_type,
        confirmed_context=confirmed_spec,
        evidence={
            "local_report": local_report,
            "current_ladder_json": current_version_json,
        },
    )
    system_prompt = _with_confirmed_context(
        INSPECTION_SYSTEM_PROMPT
        + f"\nSelected PLC model: {plc_model}\n"
        + _build_model_context(
            plc_model,
            confirmed_spec,
            compact=bool(knowledge_ctx),
        )
        + f"Inspection type: {report_type}\n"
        + workflow_prompt
        + knowledge_ctx,
        confirmed_spec,
    )
    payload = {
        "report_type": report_type,
        "plc_model": plc_model,
        "request": request,
        "local_report": local_report,
        "current_ladder_json": current_version_json,
    }
    messages = _build_clean_messages(conversation_history or [], system_prompt)
    messages.append(
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False, indent=2),
        }
    )
    try:
        response = _request_model(
            messages,
            model_name=model_name,
            effort=effort,
            stream=False,
            request_timeout=request_timeout,
            max_retries=0 if request_timeout is not None else None,
            response_contract=INSPECTION_RESPONSE,
        )
        raw = _clean_json_response(response.message.content)
        candidate = json.loads(raw)
        if not isinstance(candidate, dict):
            raise ValueError("inspection response must be a JSON object")
        return candidate
    except ResponseRejectedError:
        raise
    except Exception as error:
        print(f"inspection api request failed: {error}")
        if raise_errors:
            raise RuntimeError(f"Inspection API request failed: {error}") from error
        return None


def review_ladder(
    review_focus,
    current_version_json,
    local_report,
    **kwargs,
):
    return inspect_ladder(
        "program_review",
        {"review_focus": str(review_focus or "").strip()},
        current_version_json,
        local_report,
        **kwargs,
    )


@language_scoped
def stream_model_response(user_requirement, model_name, effort, target_mode,
                             on_reasoning_chunk=None, on_content_chunk=None,
                             is_edit_mode=False, conversation_history=None,
                             confirmed_context=None, persist_history=None,
                             task_type=None, review_mode=None,
                             confirmed_spec=None,
                             current_version_json=None,
                             plc_model=None,
                             image_attachments=None):
    """
    通过当前 ModelProvider 流式调用模型，实时返回工程推理摘要。

    参数:
        on_reasoning_chunk(token: str) — 收到推理内容片段时回调
        on_content_chunk(token: str)   — 收到输出内容片段时回调

    返回:
        (full_reasoning: str, full_content: str)
    """
    print(f"思考中(流式)... (当前模式: {effort}, 目标语言: {target_mode})")

    messages, conversation_history, should_persist = _prepare_api_call(
        user_requirement, model_name, effort, target_mode,
        is_edit_mode=is_edit_mode,
        conversation_history=conversation_history,
        confirmed_context=confirmed_context,
        confirmed_spec=confirmed_spec,
        persist_history=persist_history,
        task_type=task_type,
        review_mode=review_mode,
        current_version_json=current_version_json,
        plc_model=plc_model,
        image_attachments=image_attachments,
    )

    response = _request_model(
        messages,
        model_name=model_name,
        effort=effort,
        stream=True,
        response_contract=LADDER_RESPONSE if target_mode == "ladder" else ST_RESPONSE,
        preserved_annotations=source_annotations(current_version_json, confirmed_spec, confirmed_context),
        on_reasoning_chunk=on_reasoning_chunk,
        on_content_chunk=on_content_chunk,
    )
    full_reasoning = response.message.reasoning
    full_content = response.message.content

    # ---------- 保存历史（含思考过程） ----------
    conversation_history.append({
        "role": "assistant",
        "content": full_content,
        "reasoning": full_reasoning
    })
    if should_persist:
        _save_history(conversation_history)

    return full_reasoning, full_content


@language_scoped
def generate_model_json(user_requirement: str, model_name: str, effort: str,
                                   target_mode: str, is_edit_mode: bool = False,
                                   conversation_history=None,
                                   confirmed_context=None,
                                   confirmed_spec=None,
                                   persist_history=None,
                                   request_timeout=None,
                                   max_retries=None,
                                   raise_errors=False,
                                   task_type=None,
                                   review_mode=None,
                                   current_version_json=None,
                                   plc_model=None,
                                   image_attachments=None) -> str:
    print(f"思考中... (当前模式: {effort}, 目标语言: {target_mode})")

    messages, conversation_history, should_persist = _prepare_api_call(
        user_requirement, model_name, effort, target_mode,
        is_edit_mode=is_edit_mode,
        conversation_history=conversation_history,
        confirmed_context=confirmed_context,
        confirmed_spec=confirmed_spec,
        persist_history=persist_history,
        task_type=task_type,
        review_mode=review_mode,
        current_version_json=current_version_json,
        plc_model=plc_model,
        image_attachments=image_attachments,
    )

    try:
        response = _request_model(
            messages,
            model_name=model_name,
            effort=effort,
            stream=False,
            request_timeout=request_timeout,
            max_retries=max_retries,
            response_contract=LADDER_RESPONSE if target_mode == "ladder" else ST_RESPONSE,
            preserved_annotations=source_annotations(current_version_json, confirmed_spec, confirmed_context),
        )
        assistant_message = response.message

        conversation_history.append({
            "role": "assistant",
            "content": assistant_message.content
        })
        if should_persist:
            _save_history(conversation_history)

        raw_content = assistant_message.content.strip()
        if raw_content.startswith("```"):
            raw_content = raw_content.split("\n", 1)[1]
        if raw_content.endswith("```"):
            raw_content = raw_content.rsplit("\n", 1)[0]
        return raw_content.strip()

    except ResponseRejectedError:
        raise
    except Exception as e:
        print(f"api 接入失败: {e}")
        if raise_errors:
            raise RuntimeError(f"API request failed: {e}") from e
        return ""


def _deprecated_model_alias(name, target):
    """Keep one-release source compatibility without retaining old parsing."""

    def forward(*args, **kwargs):
        warnings.warn(
            f"api.{name} 已废弃；请改用 api.{target.__name__}。",
            DeprecationWarning,
            stacklevel=2,
        )
        return target(*args, **kwargs)

    forward.__name__ = name
    forward.__doc__ = f"Deprecated forwarding alias for {target.__name__}."
    forward.__deprecated__ = True
    return forward


# One-release source compatibility.  New application code uses only the
# vendor-neutral names; these wrappers are removed in the next release.
call_deepseek_analyze_requirement = _deprecated_model_alias(
    "call_deepseek_analyze_requirement", analyze_requirement
)
call_deepseek_analyze_streaming = _deprecated_model_alias(
    "call_deepseek_analyze_streaming", analyze_requirement_streaming
)
call_deepseek_debug_ladder = _deprecated_model_alias(
    "call_deepseek_debug_ladder", debug_ladder
)
call_deepseek_debug_evidence_diagnosis = _deprecated_model_alias(
    "call_deepseek_debug_evidence_diagnosis", debug_evidence_diagnosis
)
call_deepseek_debug_evidence_patch = _deprecated_model_alias(
    "call_deepseek_debug_evidence_patch", debug_evidence_patch
)
call_deepseek_generate_simulator_test_suite = _deprecated_model_alias(
    "call_deepseek_generate_simulator_test_suite", generate_simulator_test_suite
)
call_deepseek_multi_agent_specialist = _deprecated_model_alias(
    "call_deepseek_multi_agent_specialist", run_multi_agent_specialist
)
call_deepseek_inspection = _deprecated_model_alias(
    "call_deepseek_inspection", inspect_ladder
)
call_deepseek_review_ladder = _deprecated_model_alias(
    "call_deepseek_review_ladder", review_ladder
)
call_deepseek_streaming = _deprecated_model_alias(
    "call_deepseek_streaming", stream_model_response
)
call_deepseek_to_generate_json = _deprecated_model_alias(
    "call_deepseek_to_generate_json", generate_model_json
)
