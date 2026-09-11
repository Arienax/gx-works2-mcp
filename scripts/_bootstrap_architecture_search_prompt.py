from __future__ import annotations

from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
    print(f"applied: {label}")


root = Path(__file__).resolve().parents[1]
pattern = root / "src/pattern_library.py"
api = root / "src/api.py"
workflow = root / ".github/workflows/generation-fast-path.yml"
test_file = root / "tests/test_analysis_architecture_search.py"

# 1. Give analysis its own lightweight search-space scaffold.  It names
# architecture families but contains no full ladder examples, so it broadens
# recall without turning one implementation into a few-shot default.
replace_once(
    pattern,
    '''- Never auto-add stop or emergency-stop inputs. Use stop/e-stop only when the
  user explicitly provides or confirms the device/address.
""",
''',
    '''- Never auto-add stop or emergency-stop inputs. Use stop/e-stop only when the
  user explicitly provides or confirms the device/address.
""",
    "architecture_search": """
## Control architecture search
Before proposing approaches, internally enumerate the viable control-architecture
families for the current requirement. Consider only families that are applicable:
- direct combinational/interlock logic
- self-hold or SET/RST state retention
- bit-state machines using M/S state bits
- register-state machines using D state values
- hardware-counter versus data-register counter/control
- domain-specific pulse positioning, analog, serial, PID, or VFD structures

Candidate approaches must be materially different in state/sequence ownership or
instruction family. Merely changing device numbers, timer numbers, rung order,
contact layout, or adding an intermediate M relay that only mirrors a condition
does not create a new architecture.

For sequential, staged, or cross-scan temporal workflows, explicitly consider a
simpler direct/latch family and an explicit state-oriented family before choosing
the shortlist. Do not force either family when it does not fit. Return only the
best 1-3 materially different candidates; fewer is valid when the design space is
narrow.
""",
''',
    "add analysis architecture-search bundle",
)
replace_once(
    pattern,
    'Classify the user request before writing code: generate, edit, review, debug, explain, sfc, or io_mapping.',
    'Classify the user request before writing code: analysis, generate, edit, review, debug, explain, sfc, or io_mapping.',
    "teach workflow router the analysis task",
)
replace_once(
    pattern,
    '''        if task_type in {"generate", "edit", "repair", "debug_fix", "contract_repair"}:
            bundles.extend(["io_mapping", "output_ownership", "scan_semantics"])
''',
    '''        if task_type in {"analysis", "generate", "edit", "repair", "debug_fix", "contract_repair"}:
            bundles.extend(["io_mapping", "output_ownership", "scan_semantics"])
        if task_type == "analysis":
            bundles.append("architecture_search")
''',
    "route architecture search only to analysis",
)

# 2. Replace domain-specific candidate few-shots with explicit search rules.
api_text = api.read_text(encoding="utf-8")
start = '# 方案设计（核心！给出不同编程思路让用户选）\n'
end = '# 输出要求\n'
if api_text.count(start) != 1 or api_text.count(end) != 1:
    raise RuntimeError("analysis design markers changed")
left = api_text.index(start)
right = api_text.index(end, left)
design_block = '''# 方案设计（先搜索架构空间，再给用户选）

根据需求分析，给出 1~3 种**本质上不同的梯形图实现架构**。先在内部搜索可行的控制架构族，再筛选最适合当前需求的候选；不要从某个固定范例直接改写答案。

- 架构差异必须体现在状态/顺序的组织方式或核心指令族上，而不是仅换软元件编号、定时器编号、梯级顺序或触点排布。
- “直接逻辑”与“直接逻辑 + 一个只转存条件的辅助 M”通常属于同一架构族，不应伪装成两个方案。
- 对存在顺序、阶段、跨扫描状态或复杂时序的任务，应在内部至少考虑简单直接/锁存控制、位状态控制、寄存器状态机等适用架构，再淘汰不合适者；这不是要求必须输出状态机。
- 对定位、计数、模拟量、通讯、PID、变频器等任务，应比较会真正改变程序结构的指令/控制族，而不是制造表面不同的梯级写法。
- 不要为了凑满 3 个而输出劣质或重复方案；只有一种合理架构时可以只输出一种。
- 每种实际候选都必须填写 `generation_guide` 和可机器校验的 `generation_contract`，并让不同候选的核心 `required_structures` 或核心指令族存在架构级差异。

'''
api_text = api_text[:left] + design_block + api_text[right:]

# 3. The old JSON format example itself encoded direct logic + a register state
# machine and motion-specific questions. Make the format example deliberately
# architecture-neutral; the real response rules still require 1-3 approaches.
example_start = '返回纯JSON（不要```json包裹），格式：\n'
example_end = '\n# suggested_io 硬约束\n'
if api_text.count(example_start) != 1 or api_text.count(example_end) != 1:
    raise RuntimeError("analysis JSON example markers changed")
example_left = api_text.index(example_start) + len(example_start)
example_right = api_text.index(example_end, example_left)
neutral_example = '''{
  "summary": "一句话总结",
  "control_type": ["启停"],
  "approaches": [],
  "missing_info": [],
  "suggested_io": {},
  "hardware_config": {},
  "assumptions": [],
  "format_diagnostics": [],
  "execution_semantics": [],
  "flowchart_steps": [
    {"type":"step","label":"初始状态"}
  ]
}'''
# Insert an anti-anchoring note immediately before the parseable example marker.
format_note = (
    '下面 JSON 只展示顶层字段形状，`approaches` 故意留空以避免把某种实现暗示为默认答案；'
    '实际回复必须按上面的架构搜索规则填写 1~3 个候选方案。每个 approach 必须包含 '
    '`approach_id`、`name`、`description`、`pros`、`cons`、`generation_guide`、`generation_contract`。\n'
)
marker_pos = api_text.index(example_start)
api_text = api_text[:marker_pos] + format_note + api_text[marker_pos:example_left] + neutral_example + api_text[example_right:]

# 4. Analysis and generation have different responsibilities. Generation keeps
# following the confirmed approach; only analysis receives the search scaffold.
old_route = 'forced_task=task_type or "generate",'
route_count = api_text.count(old_route)
if route_count != 2:
    raise RuntimeError(f"expected two analysis route anchors, found {route_count}")
api_text = api_text.replace(old_route, 'forced_task=task_type or "analysis",')
api.write_text(api_text, encoding="utf-8", newline="\n")
print("applied: analysis prompt architecture-space refactor")

# 5. Lock the boundary with focused regressions.
test_text = r'''import inspect
import json

import api
from pattern_library import build_workflow_prompt


def test_analysis_router_injects_architecture_search_only_for_analysis():
    request = "FX3U输送线依次执行三个工位并带延时"
    analysis_prompt, analysis_route = build_workflow_prompt(
        request, target_mode="ladder", forced_task="analysis"
    )
    generation_prompt, generation_route = build_workflow_prompt(
        request, target_mode="ladder", forced_task="generate"
    )

    assert analysis_route.task_type == "analysis"
    assert generation_route.task_type == "generate"
    assert "## Control architecture search" in analysis_prompt
    assert "register-state machines using D state values" in analysis_prompt
    assert "adding an intermediate M relay that only mirrors a condition" in analysis_prompt
    assert "best 1-3 materially different candidates" in analysis_prompt
    assert "## Control architecture search" not in generation_prompt


def test_analysis_prompt_uses_search_rules_instead_of_domain_candidate_few_shots():
    prompt = api.ANALYSIS_SYSTEM_PROMPT
    assert "先在内部搜索可行的控制架构族" in prompt
    assert "直接逻辑 + 一个只转存条件的辅助 M" in prompt
    assert "不要为了凑满 3 个" in prompt
    assert "方案示例（分拣/顺序控制）" not in prompt
    assert "方案A「直接逻辑法」" not in prompt
    assert "方案示例（三泵轮换）" not in prompt

    example = prompt.split("返回纯JSON（不要```json包裹），格式：\n", 1)[1]
    example = example.split("\n# suggested_io", 1)[0]
    parsed = json.loads(example)
    assert parsed["approaches"] == []
    assert parsed["missing_info"] == []
    assert parsed["suggested_io"] == {}


def test_analysis_entrypoints_route_as_analysis_not_generation():
    for function in (api.analyze_requirement, api.analyze_requirement_streaming):
        source = inspect.getsource(function)
        assert 'forced_task=task_type or "analysis"' in source
        assert 'forced_task=task_type or "generate"' not in source


def test_generation_system_prompt_does_not_reopen_architecture_search():
    prompt = api._select_system_prompt(
        "ladder",
        user_requirement="FX3U输送线依次执行三个工位并带延时",
        task_type="generate",
        plc_model="FX3U",
    )
    assert "## Control architecture search" not in prompt
'''
if test_file.exists():
    raise RuntimeError("test_analysis_architecture_search.py already exists")
test_file.write_text(test_text, encoding="utf-8", newline="\n")
print("created: analysis architecture-search regression tests")

# Keep the new boundary in the long-lived Windows CI used by main/PRs.
replace_once(
    workflow,
    '''            tests/test_generation_repair_workflow.py `
            tests/test_user_confirmed_generation_repair.py `
''',
    '''            tests/test_generation_repair_workflow.py `
            tests/test_user_confirmed_generation_repair.py `
            tests/test_analysis_architecture_search.py `
''',
    "add architecture-search regression to formal CI",
)
