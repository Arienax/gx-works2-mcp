from __future__ import annotations

from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        print(f"skip: {label}")
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
    print(f"applied: {label}")


root = Path(__file__).resolve().parents[1]
api = root / "src/api.py"
pattern = root / "src/pattern_library.py"
motion_test = root / "tests/test_motion_control_regressions.py"
workflow = root / ".github/workflows/generation-fast-path.yml"
readme = root / "resources/knowledge/README.md"
test_file = root / "tests/test_analysis_design_rag.py"

# Analysis is the phase that intentionally searches the local knowledge base.
# In adaptive mode generic PLC requirements previously missed RAG because they
# contained no opcode/module/error signal. Keep other task gating unchanged.
replace_once(
    api,
    '''    should_lookup, lookup_reason = manual_lookup_decision(query)\n    if not should_lookup:\n''',
    '''    should_lookup, lookup_reason = manual_lookup_decision(query)\n    if (\n        not should_lookup\n        and normalized_task == "analysis"\n        and resolve_context_policy().manuals == "adaptive"\n        and query.strip()\n    ):\n        should_lookup, lookup_reason = True, "analysis_design_retrieval"\n    if not should_lookup:\n''',
    "make adaptive analysis consult SQLite",
)

# Route phase-one work as analysis so task-scoped SQLite chunks can participate.
api_text = api.read_text(encoding="utf-8")
old_route = 'forced_task=task_type or "generate",'
count = api_text.count(old_route)
if count != 2:
    raise RuntimeError(f"analysis route anchors changed: {count}")
api_text = api_text.replace(old_route, 'forced_task=task_type or "analysis",')

# Remove implementation-specific candidate few-shots. The prompt owns search
# behavior; concrete architecture knowledge now comes from SQLite evidence.
start = '# 方案设计（核心！给出不同编程思路让用户选）\n'
end = '# 输出要求\n'
if api_text.count(start) != 1 or api_text.count(end) != 1:
    raise RuntimeError("analysis design-section markers changed")
left = api_text.index(start)
right = api_text.index(end, left)
design_block = '''# 方案设计（检索知识后再给用户选）\n\n在输出 `approaches` 前，先结合当前需求、PLC 型号以及 `Retrieved PLC knowledge` 中检索到的设计知识，在内部搜索适用的实现架构，再筛选 1~3 个候选。\n\n- 候选必须在状态/顺序组织方式、核心数据模型或核心指令族上存在本质差异。\n- 仅更换软元件编号、定时器编号、梯级顺序、触点排布，或增加一个只复制同一条件的中间继电器，不算新的架构方案。\n- 不得为了凑足数量制造重复方案；设计空间很窄时允许只给 1 个。\n- 不要因为 system prompt 中出现过某个实现方式就强制采用它；具体架构的适用条件、优缺点和实现事实以当前需求与检索知识为依据。\n- 每个实际候选必须包含 `generation_guide` 和可机器校验的 `generation_contract`，不同候选的 contract 应能体现其架构级差异。\n\n'''
api_text = api_text[:left] + design_block + api_text[right:]

# The old shape example itself contained two concrete architectures and motion
# parameters, which acted as a second few-shot even after prose examples were
# removed. Keep only a parseable top-level shape example.
example_start = '返回纯JSON（不要```json包裹），格式：\n'
example_end = '\n# suggested_io 硬约束\n'
if api_text.count(example_start) != 1 or api_text.count(example_end) != 1:
    raise RuntimeError("analysis JSON example markers changed")
example_left = api_text.index(example_start) + len(example_start)
example_right = api_text.index(example_end, example_left)
neutral = '''{\n  "summary": "一句话总结",\n  "control_type": ["启停"],\n  "approaches": [],\n  "missing_info": [],\n  "suggested_io": {},\n  "hardware_config": {},\n  "assumptions": [],\n  "format_diagnostics": [],\n  "execution_semantics": [],\n  "flowchart_steps": [\n    {"type":"step","label":"初始状态"}\n  ]\n}'''
note = (
    '下面 JSON 仅展示顶层字段形状，`approaches` 故意留空以避免把某种实现写成默认答案；'
    '实际回复必须根据当前需求与检索知识填写 1~3 个候选。每个 approach 必须包含 '
    '`approach_id`、`name`、`description`、`pros`、`cons`、`generation_guide`、`generation_contract`。\n'
)
marker = api_text.index(example_start)
api_text = api_text[:marker] + note + api_text[marker:example_left] + neutral + api_text[example_right:]
api.write_text(api_text, encoding="utf-8", newline="\n")
print("applied: replace analysis few-shots with retrieval-driven meta rules")

# The workflow router needs an analysis task name but receives no concrete
# architecture list here. Existing generic scan/I/O bundles remain unchanged.
replace_once(
    pattern,
    'Classify the user request before writing code: generate, edit, review, debug, explain, sfc, or io_mapping.',
    'Classify the user request before writing code: analysis, generate, edit, review, debug, explain, sfc, or io_mapping.',
    "teach workflow router analysis task",
)
replace_once(
    pattern,
    '''        if task_type in {"generate", "edit", "repair", "debug_fix", "contract_repair"}:\n            bundles.extend(["io_mapping", "output_ownership", "scan_semantics"])\n''',
    '''        if task_type in {"analysis", "generate", "edit", "repair", "debug_fix", "contract_repair"}:\n            bundles.extend(["io_mapping", "output_ownership", "scan_semantics"])\n''',
    "retain generic workflow knowledge for analysis",
)

# D8345 is an official positioning fact and must be tested through RAG rather
# than requiring it to be duplicated inside ANALYSIS_SYSTEM_PROMPT.
replace_once(
    motion_test,
    '    assert "D8345是回原点爬行速度" in prompt\n',
    '',
    "remove prompt-owned D8345 knowledge assertion",
)

# Document the curated source in the reproducible knowledge build pipeline.
replace_once(
    readme,
    '''当前打包的第三方支持知识源：\n''',
    '''当前内置的分析设计知识源：\n\n- `design_patterns.json`：人工整理的 PLC 控制架构选择知识，仅以 `task_types=analysis` 写入 SQLite；它描述方案之间的结构差异、适用条件与取舍，不作为 PLC 型号/指令事实的权威来源。\n\n当前打包的第三方支持知识源：\n''',
    "document curated design source",
)
replace_once(
    readme,
    '''python tools/build_fx3u_knowledge_v3.py\npython tools/import_gxw2_skill.py\n''',
    '''python tools/build_fx3u_knowledge_v3.py\npython tools/import_design_patterns.py\npython tools/import_gxw2_skill.py\n''',
    "document design import build step",
)

# Focused contract tests: retrieval policy, task scoping and anti-anchoring.
test_text = r'''import inspect
import json

import api
import knowledge_retriever
from pattern_library import build_workflow_prompt
from prompt_context_policy import context_policy_scope


def test_phase_one_routes_as_analysis():
    for function in (api.analyze_requirement, api.analyze_requirement_streaming):
        source = inspect.getsource(function)
        assert 'forced_task=task_type or "analysis"' in source
        assert 'forced_task=task_type or "generate"' not in source


def test_analysis_prompt_has_meta_search_rules_without_candidate_few_shots():
    prompt = api.ANALYSIS_SYSTEM_PROMPT
    assert "Retrieved PLC knowledge" in prompt
    assert "不算新的架构方案" in prompt
    assert "设计空间很窄时允许只给 1 个" in prompt
    assert "方案示例（分拣/顺序控制）" not in prompt
    assert "方案A「直接逻辑法」" not in prompt
    assert "方案示例（三泵轮换）" not in prompt

    example = prompt.split("返回纯JSON（不要```json包裹），格式：\n", 1)[1]
    example = example.split("\n# suggested_io", 1)[0]
    parsed = json.loads(example)
    assert parsed["approaches"] == []
    assert parsed["missing_info"] == []
    assert parsed["suggested_io"] == {}


def test_adaptive_analysis_forces_sqlite_lookup_but_generic_generation_does_not(monkeypatch):
    calls = []

    def fake_context(query, **kwargs):
        calls.append((query, kwargs))
        return "# retrieved"

    monkeypatch.setattr(knowledge_retriever, "build_knowledge_context", fake_context)
    with context_policy_scope("adaptive"):
        result = api._build_knowledge_context(
            "普通三工位顺序控制",
            plc_model="FX3U",
            task_type="analysis",
        )
    assert "# retrieved" in result
    assert calls and calls[-1][1]["task_type"] == "analysis"

    calls.clear()
    with context_policy_scope("adaptive"):
        result = api._build_knowledge_context(
            "普通三工位顺序控制",
            plc_model="FX3U",
            task_type="generate",
        )
    assert result == ""
    assert calls == []


def test_workflow_router_marks_analysis_without_embedding_architecture_catalog():
    prompt, route = build_workflow_prompt(
        "FX3U 三工位依次执行并延时",
        target_mode="ladder",
        forced_task="analysis",
    )
    assert route.task_type == "analysis"
    assert "task_type: analysis" in prompt
    assert "Control architecture search" not in prompt


def test_bundled_design_knowledge_is_analysis_scoped():
    query = "FX3U 三个工位依次执行，包含多阶段顺序和延时，应该如何组织控制架构"
    results = knowledge_retriever.retrieve_knowledge(
        query,
        plc_model="FX3U",
        task_type="analysis",
        top_k=8,
        char_budget=16000,
    )
    curated = [item for item in results if item.get("manual_id") == "curated_control_design"]
    assert curated
    assert any(item.get("chunk_type") == "design_pattern" for item in curated)
    assert any("状态" in item.get("text", "") or "架构" in item.get("text", "") for item in curated)

    generation = knowledge_retriever.retrieve_knowledge(
        query,
        plc_model="FX3U",
        task_type="generate",
        top_k=20,
        char_budget=30000,
    )
    assert all(item.get("manual_id") != "curated_control_design" for item in generation)


def test_motion_parameter_fact_remains_owned_by_official_sqlite_manual():
    results = knowledge_retriever.retrieve_knowledge(
        "FX3U D8345 DRVI 最高速度 回原点 爬行速度",
        plc_model="FX3U",
        task_type="analysis",
        top_k=8,
        char_budget=20000,
    )
    assert any(item.get("manual_id") == "fx3_positioning_k" for item in results)
    assert any("D8345" in item.get("text", "") for item in results)
'''
if test_file.exists():
    raise RuntimeError("tests/test_analysis_design_rag.py already exists")
test_file.write_text(test_text, encoding="utf-8", newline="\n")
print("created: analysis design RAG tests")

replace_once(
    workflow,
    '''            tests/test_user_confirmed_generation_repair.py `\n            tests/test_generation_delivery.py `\n''',
    '''            tests/test_user_confirmed_generation_repair.py `\n            tests/test_analysis_design_rag.py `\n            tests/test_generation_delivery.py `\n''',
    "add design RAG regression to formal CI",
)
