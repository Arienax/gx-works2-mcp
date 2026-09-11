from pathlib import Path

root = Path(__file__).resolve().parents[1]
api = root / "src/api.py"
motion_test = root / "tests/test_motion_control_regressions.py"
test_file = root / "tests/test_analysis_design_rag.py"

text = api.read_text(encoding="utf-8")
old = '''    query = _build_knowledge_query(primary_query, confirmed_context, evidence)\n    should_lookup, lookup_reason = manual_lookup_decision(query)\n'''
new = '''    query = _build_knowledge_query(primary_query, confirmed_context, evidence)\n    retrieval_query = query\n    if normalized_task == "analysis" and query.strip():\n        # Retrieval-only routing hint. Concrete architecture families and their\n        # trade-offs live in SQLite, not in the system prompt or this code.\n        retrieval_query = query + "\\nPLC 梯形图 控制架构 方案设计"\n    should_lookup, lookup_reason = manual_lookup_decision(retrieval_query)\n'''
if text.count(old) != 1:
    raise RuntimeError(f"knowledge query anchor count={text.count(old)}")
text = text.replace(old, new, 1)

old = '''            query,\n            plc_model=plc_model,\n            task_type=normalized_task,\n'''
new = '''            retrieval_query,\n            plc_model=plc_model,\n            task_type=normalized_task,\n'''
if text.count(old) != 1:
    raise RuntimeError(f"retrieval call anchor count={text.count(old)}")
text = text.replace(old, new, 1)

old = '''        "# Retrieved-manual precedence\\n"\n        "Use retrieved blocks for PLC platform and instruction facts. Priority "\n'''
new = '''        "# Retrieved-knowledge precedence\\n"\n        "Use retrieved blocks as read-only PLC evidence relevant to the current task. "\n        "Official manual evidence is authoritative for platform, device and instruction facts; "\n        "analysis-scoped curated design evidence describes design trade-offs only and must not "\n        "override confirmed project choices or official manual facts. Priority "\n'''
if text.count(old) != 1:
    raise RuntimeError(f"precedence anchor count={text.count(old)}")
text = text.replace(old, new, 1)
api.write_text(text, encoding="utf-8", newline="\n")
print("applied: analysis retrieval query hint and knowledge authority boundary")

# Remove the obsolete regression that required one official manual fact to be
# duplicated literally in api.py. The replacement test verifies SQLite owns it.
text = motion_test.read_text(encoding="utf-8")
line = '    assert "D8345是回原点爬行速度" in prompt\n'
if line not in text:
    raise RuntimeError("D8345 prompt assertion not found")
motion_test.write_text(text.replace(line, "", 1), encoding="utf-8", newline="\n")
print("applied: move D8345 regression from prompt to SQLite")

# Strengthen the focused test so the actual production top_k=4 budget must
# surface the curated design source, not merely a generous diagnostic top_k.
text = test_file.read_text(encoding="utf-8")
text = text.replace('        top_k=8,\n        char_budget=16000,', '        top_k=4,\n        char_budget=7000,', 1)
text = text.replace(
    '    assert any(item.get("chunk_type") == "design_pattern" for item in curated)\n',
    '    assert any(item.get("chunk_type") == "design_pattern" for item in curated)\n'
    '    assert len(curated) <= 3\n',
    1,
)
test_file.write_text(text, encoding="utf-8", newline="\n")
print("applied: enforce production-sized analysis retrieval test")
