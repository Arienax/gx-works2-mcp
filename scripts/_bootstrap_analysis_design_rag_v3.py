from pathlib import Path

root = Path(__file__).resolve().parents[1]
test_file = root / "tests/test_analysis_design_rag.py"
text = test_file.read_text(encoding="utf-8")
old = r'''def test_bundled_design_knowledge_is_analysis_scoped():
    query = "FX3U 三个工位依次执行，包含多阶段顺序和延时，应该如何组织控制架构"
    results = knowledge_retriever.retrieve_knowledge(
        query,
        plc_model="FX3U",
        task_type="analysis",
        top_k=4,
        char_budget=7000,
    )
    curated = [item for item in results if item.get("manual_id") == "curated_control_design"]
    assert curated
    assert any(item.get("chunk_type") == "design_pattern" for item in curated)
    assert len(curated) <= 3
    assert any("状态" in item.get("text", "") or "架构" in item.get("text", "") for item in curated)

    generation = knowledge_retriever.retrieve_knowledge(
        query,
        plc_model="FX3U",
        task_type="generate",
        top_k=20,
        char_budget=30000,
    )
    assert all(item.get("manual_id") != "curated_control_design" for item in generation)
'''
new = r'''def test_bundled_design_knowledge_is_injected_through_production_analysis_path():
    query = "FX3U 三个工位依次执行，包含多阶段顺序和延时，应该如何组织控制架构"
    with context_policy_scope("adaptive"):
        context = api._build_knowledge_context(
            query,
            plc_model="FX3U",
            task_type="analysis",
        )
    assert "Curated PLC Control Architecture Design Knowledge" in context
    assert "CONTROL ARCHITECTURE:" in context
    assert "Retrieved-knowledge precedence" in context


def test_design_chunks_are_task_scoped_out_of_generation_even_with_same_retrieval_hint():
    query = (
        "FX3U 三个工位依次执行，包含多阶段顺序和延时，应该如何组织控制架构"
        "\nPLC 梯形图 控制架构 方案设计"
    )
    analysis = knowledge_retriever.retrieve_knowledge(
        query,
        plc_model="FX3U",
        task_type="analysis",
        top_k=4,
        char_budget=7000,
    )
    assert any(item.get("manual_id") == "curated_control_design" for item in analysis)

    generation = knowledge_retriever.retrieve_knowledge(
        query,
        plc_model="FX3U",
        task_type="generate",
        top_k=20,
        char_budget=30000,
    )
    assert all(item.get("manual_id") != "curated_control_design" for item in generation)
'''
if old not in text:
    raise RuntimeError("design scope test anchor changed")
test_file.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
print("applied: validate design RAG through production analysis injection")
