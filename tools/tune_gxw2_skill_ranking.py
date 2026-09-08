#!/usr/bin/env python3
"""Add narrow concept-routing entities for gxw2-skill supporting chunks.

Phase 2 keeps gxw2-skill out of authoritative structured stores.  This script
adds a small, idempotent ``skill_concept`` layer to ``entity_index`` so ST rules,
data-type guidance, and compatibility notes can enter the existing hybrid
candidate pool when a query names a relevant GX Works2 concept.

The script does not change chunks, dense vectors, manual priority, or any
Mitsubishi official structured record.  It is therefore safe to run after the
third-party import and does not make dense embeddings stale.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
import sqlite3


SOURCE_MANUAL_ID = "gxw2_skill_1_6_1"
ENTITY_TYPE = "skill_concept"

# Each route maps a query-visible exact term to markers that identify the most
# relevant supporting chunk.  Terms are deliberately narrow: they should route
# a user to a rule/reference page, not turn the third-party source into a global
# authority.
CONCEPT_ROUTES: dict[str, dict[str, tuple[str, ...]]] = {
    "st_rule": {
        "CONTINUE": ("continue",),
        "VAR_IN_OUT": ("var_in_out",),
        "CASE": ("case statement", "case ranges", "named case"),
        "TON": ("assignment operator", "tondelay", "ton("),
        "SR": ("sr/rs", "sr`, `rs", "bistable"),
        "RS": ("sr/rs", "sr`, `rs", "bistable"),
        "ARRAY": ("array[*]", "variable-length arrays"),
        "NEW": ("__new", "dynamic memory"),
        "DELETE": ("__delete", "dynamic memory"),
        "FB": ("fb/fun/prg", "function block", "fb instance"),
        "FUN": ("fb/fun/prg", "fun name", "function overloading"),
        "PRG_INIT": ("prg_init",),
        "PRG_MAIN": ("prg_main",),
        "PRG_PROCESS": ("prg_process",),
        "FB_MOTOR": ("fb_motor",),
        "FBMOTOR": ("fbmotor",),
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
    required = {"chunks", "entity_index", "manuals"}
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
            SELECT id,chunk_type,text,plc_models
            FROM chunks
            WHERE manual_id=? AND chunk_type IN ('st_rule','data_type','compatibility')
            """,
            (manual_id,),
        ).fetchall()

        inserted = 0
        routed_concepts: set[str] = set()
        per_type: defaultdict[str, int] = defaultdict(int)
        for chunk_id, chunk_type, text, plc_models in rows:
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
                        int(chunk_id),
                        1,
                    ),
                )
                inserted += 1
                routed_concepts.add(concept)
                per_type[str(chunk_type)] += 1

        connection.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
            ("external_source_gxw2_skill_routing", "concept_entities_v1"),
        )
        connection.commit()

        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"database integrity check failed: {integrity}")

    return {
        "entities": inserted,
        "concepts": len(routed_concepts),
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
        f"st_rule={stats['st_rule']} data_type={stats['data_type']} "
        f"compatibility={stats['compatibility']}"
    )
    print("Dense embeddings remain valid; no dense rebuild is required for this step.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
