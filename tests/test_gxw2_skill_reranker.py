import knowledge_retriever as retriever


def _candidate(chunk_type, *, task_signal=True, matched="CONTINUE"):
    return {
        "manual_type": "third_party_skill",
        "chunk_type": chunk_type,
        "retrieval_signals": ["entity", "vector"] if task_signal else ["vector"],
        "matched_entity": matched,
        "score": 1500.0,
    }


def test_supporting_boost_requires_third_party_entity_route():
    candidate = _candidate("st_rule")
    assert retriever._gxw2_supporting_boost(candidate, "st") > 0

    no_entity = _candidate("st_rule", task_signal=False)
    assert retriever._gxw2_supporting_boost(no_entity, "st") == 0

    official = dict(candidate, manual_type="programming")
    assert retriever._gxw2_supporting_boost(official, "st") == 0


def test_supporting_boost_is_task_and_chunk_scoped():
    assert retriever._gxw2_supporting_boost(_candidate("st_rule"), "st") == 320.0
    assert retriever._gxw2_supporting_boost(_candidate("data_type", matched="DINT"), "analysis") == 220.0
    assert retriever._gxw2_supporting_boost(_candidate("compatibility", matched="FX3S"), "analysis") == 300.0
    assert retriever._gxw2_supporting_boost(_candidate("skill_instruction", matched="MOV"), "st") == 0
    assert retriever._gxw2_supporting_boost(_candidate("st_rule"), "debug") == 0


def test_supporting_boost_rejects_nonconcept_entity_hits():
    candidate = _candidate("st_rule", matched="MOV")
    assert retriever._gxw2_supporting_boost(candidate, "st") == 0


def test_weak_concepts_do_not_expand_generic_requests():
    assert retriever._query_has_gxw2_skill_concept("please revise this program") is False
    assert retriever._query_has_gxw2_skill_concept("check the output") is False
    assert retriever._query_has_gxw2_skill_concept("memory usage") is False


def test_weak_concepts_expand_when_gxworks_context_is_explicit():
    assert retriever._query_has_gxw2_skill_concept("FX3U GX Works2 ST program structure") is True
    assert retriever._query_has_gxw2_skill_concept("GX Works2 STRING support") is True


def test_strong_skill_concepts_expand_without_generic_context():
    assert retriever._query_has_gxw2_skill_concept("VAR_IN_OUT supported?") is True
    assert retriever._query_has_gxw2_skill_concept("INT_TO_REAL_E return value") is True
