"""Phase-2c scoped reranking for gxw2-skill supporting evidence.

This module intentionally does not change the base retrieval engine. It only
boosts third-party supporting chunks when they were reached through an exact
skill concept entity and the requested task matches the chunk role.
"""

from __future__ import annotations


_GXW2_SKILL_CONCEPTS = {
    "CONTINUE", "VAR_IN_OUT", "CASE", "RANGE", "LABEL", "TON", "OUTPUT",
    "SR", "RS", "ARRAY", "NEW", "DELETE", "DYNAMIC", "MEMORY", "FB", "FUN",
    "PROGRAM", "POU", "INSTANCE", "PRG_INIT", "PRG_MAIN", "PRG_PROCESS",
    "FB_MOTOR", "FBMOTOR", "COMMENT", "COMMENTS", "STRUCTURED", "TEXT",
    "LREAL", "WSTRING", "LTIME", "REF_TO", "DINT", "DWORD", "REAL", "STRING",
    "TIME", "K100", "HFF", "E3", "INT_TO_REAL_E", "FX3S", "WORKS3",
}

_BOOSTS = {
    "st": {
        "st_rule": 320.0,
        "data_type": 280.0,
        "compatibility": 240.0,
    },
    "generate": {
        "st_rule": 280.0,
        "data_type": 240.0,
        "compatibility": 160.0,
    },
    "edit": {
        "st_rule": 280.0,
        "data_type": 240.0,
    },
    "analysis": {
        "data_type": 220.0,
        "compatibility": 300.0,
    },
}


def supporting_boost(candidate: dict, task_type: str) -> float:
    if str(candidate.get("manual_type") or "").casefold() != "third_party_skill":
        return 0.0
    if "entity" not in set(candidate.get("retrieval_signals") or ()):
        return 0.0
    matched = str(candidate.get("matched_entity") or "").strip().upper()
    if matched not in _GXW2_SKILL_CONCEPTS:
        return 0.0
    task = str(task_type or "").casefold()
    chunk_type = str(candidate.get("chunk_type") or "").casefold()
    return float(_BOOSTS.get(task, {}).get(chunk_type, 0.0))


def rerank(results: list[dict], task_type: str) -> list[dict]:
    ranked = []
    for result in results:
        candidate = dict(result)
        boost = supporting_boost(candidate, task_type)
        if boost:
            candidate["gxw2_supporting_boost"] = boost
            candidate["score"] = round(float(candidate.get("score") or 0.0) + boost, 4)
        ranked.append(candidate)
    ranked.sort(
        key=lambda item: (
            -float(item.get("score") or 0.0),
            -int(item.get("manual_priority") or 0),
            int(item.get("pdf_page") or 0),
            str(item.get("id") or ""),
        )
    )
    return ranked


__all__ = ["supporting_boost", "rerank"]
