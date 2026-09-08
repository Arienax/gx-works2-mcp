#!/usr/bin/env python3
"""Add narrow concept-routing metadata for gxw2-skill supporting chunks.

Phase 2 keeps gxw2-skill out of authoritative structured stores. This script
adds a small, idempotent ``skill_concept`` layer to ``entity_index`` so ST rules,
data-type guidance, and compatibility notes can enter the existing hybrid
candidate pool when a query names a relevant GX Works2 concept.

Phase 2b also mirrors those derived concept tokens into the chunk ``entities``
search field and rebuilds FTS5. This strengthens BM25/entity cross-signals
without changing chunk text, dense vectors, manual priority, or any Mitsubishi
official structured record. Dense embeddings therefore remain valid.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
import sqlite3


SOURCE_MANUAL_ID = "gxw2_skill_1_6_1"
ENTITY_TYPE = "skill_concept"

# Each route maps a query-visible exact term to markers that identify the most
# relevant supporting chunk. Terms are deliberately narrow: they should route
# a user to a rule/reference page, not turn the third-party source into a global
# authority.
CONCEPT_ROUTES: dict[str, dict[str, tuple[str, ...]]] = {
    "st_rule": {
        "CONTINUE": ("continue",),
        "VAR_IN_OUT": ("var_in_out",),
        "CASE": ("case statement", "case ranges", "named case"),
        "RANGE": ("case ranges", "1..5"),
        "LABEL": ("named case", "integer labels"),
        "TON": ("assignment operator", "tondelay", "ton("),
        "OUTPUT": ("assignment operator", "fb outputs"),
        "SR": ("sr/rs", "sr`, `rs", "bistable"),
        "RS": ("sr/rs", "sr`, `rs", "bistable"),
        "ARRAY": ("array[*]", "variable-length arrays"),
        "NEW": ("__new", "dynamic memory"),
        "DELETE": ("__delete", "dynamic memory"),
        "DYNAMIC": ("dynamic memory", "__new", "__delete"),
        "MEMORY": ("dynamic memory", "__new", "__delete"),
        "FB": ("fb/fun/prg", "function block", "fb instance"),
        "FUN": ("fb/fun/prg", "fun name", "function overloading"),
        "PROGRAM": ("3-program structure", "program pou", "prg_"),
        "POU": ("pou", "fb/fun/prg", "program pou"),
        "INSTANCE": ("fb instance", "instances are declared"),
        "PRG_INIT": ("prg_init",),
        "PRG_MAIN": ("prg_main",),
        "PRG_PROCESS": ("prg_process",),
        "FB_MOTOR": ("fb_motor",),
        "FBMOTOR": ("fbmotor",),
        "COMMENT": ("comment style", "line comments", "comments:"),
        "COMMENTS": ("comment style", "line comments", "comments:"),
        # Chinese queries commonly retain the English phrase "Structured Text".
        # Route those two exact tokens specifically to the comment-style rule
        # chunk instead of giving every skill chunk a generic ST boost.
        "STRUCTURED": ("comment style", "line comments", "comments:"),
        "TEXT": ("comment style", "line comments", "comments:"),
    },
    "data_type": {
        "LREAL": ("lreal",),
        "WSTRING": ("wstring",),
        "LTIME": ("ltime",),
        "REF_TO": ("ref_to",),
        "DINT": ("memory consumption", "d registers consumed"),
        "DWORD": ("memory consumption", "d registers consumed"),
        "REAL": ("memory consumption", "d registers consumed"),
        "STRING": ("elementary types", "unsupported types", "string conversions"),
        "TIME": ("elementary types", "time conversions"),
        "K100": ("mitsubishi literal notation", "literal examples"),
        "HFF": ("mitsubishi literal notation", "literal examples"),
        "E3": ("mitsubishi literal notation", "literal examples"),
        "INT_TO_REAL_E": ("int_to_real_e", "_e postfix pattern"),
    },
    "compatibility": {
        "STRING": ("feature matrix", "string functions"),
        "FX3S": ("device ranges", "fx3s"),
        "WORKS3": ("gx works 2 vs gx works 3", "gx works 3"),
    },
}

TASK_SCOPE = {
    "st_rule": "st,generate,edit",
    "data_type": "st,generate,edit,analysis",
    "compatibility": "st,generate,analysis",
}


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        type=Path,
        default=root / "resources" / "knowledge" / "fx3u_knowledge.sqlite",
    )
    parser.add_argument("--manual-id", default=SOURCE_MANUAL_ID)
    return parser.parse_args()


def _validate_schema(connection: sqlite3.Connection) -> None:
    required = {"chunks", "entity_index", "manuals", "chunks_fts"}
    present = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        )
    }
    missing = sorted(required - present)
    if missing:
        raise RuntimeError(f"knowledge database missing: {', '.join(missing)}")


def _marker_matches(text: str, markers: tuple[str, ...]) -> bool:
    haystack = text.casefold()
    return any(marker.casefold() in haystack for marker in markers)


def _merge_entity_tokens(existing: str, concepts: set[str]) -> str:
    tokens = [token for token in str(existing or "").split() if token]
    seen = {token.casefold() for token in tokens}
    for concept in sorted(concepts):
        if concept.casefold() not in seen:
            tokens.append(concept)
            seen.add(concept.casefold())
    return " ".join(tokens)


def tune_database(database: Path, manual_id: str = SOURCE_MANUAL_ID) -> dict[str, int]:
    database = database.expanduser().resolve()
    if not database.is_file():
        raise FileNotFoundError(database)

    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        _validate_schema(connection)

        manual = connection.execute(
            "SELECT manual_type FROM manuals WHERE manual_id=?",
            (manual_id,),
        ).fetchone()
        if manual is None:
            raise RuntimeError(
                f"gxw2-skill source {manual_id!r} is not imported; "
                "run tools/import_gxw2_skill.py first"
            )
        if str(manual[0]) != "third_party_skill":
            raise RuntimeError(
                f"refusing to tune non-third-party source {manual_id!r}"
            )

        # Idempotent replacement of this derived routing layer only.
        connection.execute(
            "DELETE FROM entity_index WHERE manual_id=? AND entity_type=?",
            (manual_id, ENTITY_TYPE),
        )

        rows = connection.execute(
            """
            SELECT id,chunk_type,text,plc_models,entities
            FROM chunks
            WHERE manual_id=? AND chunk_type IN ('st_rule','data_type','compatibility')
            """,
            (manual_id,),
        ).fetchall()

        inserted = 0
        routed_concepts: set[str] = set()
        per_type: defaultdict[str, int] = defaultdict(int)
        concepts_by_chunk: defaultdict[int, set[str]] = defaultdict(set)
        entities_by_chunk: dict[int, str] = {}

        for chunk_id, chunk_type, text, plc_models, existing_entities in rows:
            chunk_id = int(chunk_id)
            entities_by_chunk[chunk_id] = str(existing_entities or "")
            routes = CONCEPT_ROUTES.get(str(chunk_type), {})
            for concept, markers in routes.items():
                if not _marker_matches(str(text or ""), markers):
                    continue
                connection.execute(
                    """
                    INSERT OR REPLACE INTO entity_index(
                        entity_norm,entity,entity_type,plc_models,task_types,
                        manual_id,chunk_id,occurrences
                    ) VALUES(?,?,?,?,?,?,?,?)
                    """,
                    (
                        concept.casefold(),
                        concept,
                        ENTITY_TYPE,
                        str(plc_models or ""),
                        TASK_SCOPE[str(chunk_type)],
                        manual_id,
                        chunk_id,
                        1,
                    ),
                )
                inserted += 1
                routed_concepts.add(concept)
                per_type[str(chunk_type)] += 1
                concepts_by_chunk[chunk_id].add(concept)

        # ``entities`` is already a derived lexical-search field. Mirroring the
        # route concepts into it gives the same supporting chunk both an entity
        # signal and a stronger BM25 signal. Chunk text/text_sha256 are untouched,
        # so the dense sidecar remains valid.
        fts_chunks = 0
        for chunk_id, concepts in concepts_by_chunk.items():
            merged = _merge_entity_tokens(entities_by_chunk.get(chunk_id, ""), concepts)
            connection.execute(
                "UPDATE chunks SET entities=? WHERE id=?",
                (merged, chunk_id),
            )
            fts_chunks += 1

        connection.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
        connection.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
            ("external_source_gxw2_skill_routing", "concept_entities_fts_v2"),
        )
        connection.commit()

        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"database integrity check failed: {integrity}")

    return {
        "entities": inserted,
        "concepts": len(routed_concepts),
        "fts_chunks": fts_chunks,
        "st_rule": per_type["st_rule"],
        "data_type": per_type["data_type"],
        "compatibility": per_type["compatibility"],
    }


def main() -> int:
    args = parse_args()
    stats = tune_database(args.database, args.manual_id)
    print(
        "gxw2-skill ranking routes added: "
        f"entities={stats['entities']} concepts={stats['concepts']} "
        f"fts_chunks={stats['fts_chunks']} st_rule={stats['st_rule']} "
        f"data_type={stats['data_type']} compatibility={stats['compatibility']}"
    )
    print("FTS5 rebuilt; dense embeddings remain valid and do not need rebuilding.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
