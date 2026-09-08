from pathlib import Path
import sqlite3

from tools.tune_gxw2_skill_ranking import tune_database


def _create_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys=ON;
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
            CREATE TABLE manuals (
                manual_id TEXT PRIMARY KEY,
                manual_type TEXT NOT NULL
            ) WITHOUT ROWID;
            CREATE TABLE chunks (
                id INTEGER PRIMARY KEY,
                manual_id TEXT NOT NULL REFERENCES manuals(manual_id) ON DELETE CASCADE,
                chunk_type TEXT NOT NULL,
                text TEXT NOT NULL,
                plc_models TEXT NOT NULL
            );
            CREATE TABLE entity_index (
                entity_norm TEXT NOT NULL,
                entity TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                plc_models TEXT NOT NULL,
                task_types TEXT NOT NULL,
                manual_id TEXT NOT NULL REFERENCES manuals(manual_id) ON DELETE CASCADE,
                chunk_id INTEGER NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
                occurrences INTEGER NOT NULL,
                PRIMARY KEY(entity_norm, entity_type, chunk_id)
            ) WITHOUT ROWID;
            """
        )
        connection.execute(
            "INSERT INTO manuals(manual_id,manual_type) VALUES(?,?)",
            ("gxw2_skill_1_6_1", "third_party_skill"),
        )
        connection.execute(
            "INSERT INTO manuals(manual_id,manual_type) VALUES(?,?)",
            ("official", "programming"),
        )
        connection.executemany(
            "INSERT INTO chunks(id,manual_id,chunk_type,text,plc_models) VALUES(?,?,?,?,?)",
            [
                (
                    1,
                    "gxw2_skill_1_6_1",
                    "st_rule",
                    "No CONTINUE. Comment Style uses block comments. VAR_IN_OUT is unsupported.",
                    "FX3U,FX3G,FX3S",
                ),
                (
                    2,
                    "gxw2_skill_1_6_1",
                    "data_type",
                    "Unsupported Types include LREAL and WSTRING. Memory Consumption: DINT DWORD REAL.",
                    "FX3U,FX3G,FX3S",
                ),
                (
                    3,
                    "gxw2_skill_1_6_1",
                    "compatibility",
                    "Feature Matrix STRING. Device Ranges FX3S. GX Works 2 vs GX Works 3.",
                    "FX3U,FX3G,FX3S",
                ),
                (
                    4,
                    "official",
                    "instruction",
                    "CONTINUE STRING FX3S GX Works 3",
                    "FX3U",
                ),
            ],
        )
        connection.execute(
            """
            INSERT INTO entity_index(
                entity_norm,entity,entity_type,plc_models,task_types,
                manual_id,chunk_id,occurrences
            ) VALUES('mov','MOV','instruction','FX3U','*','official',4,1)
            """
        )
        connection.commit()


def test_tune_database_adds_scoped_supporting_concepts_and_is_idempotent(tmp_path):
    database = tmp_path / "knowledge.sqlite"
    _create_database(database)

    first = tune_database(database)
    second = tune_database(database)

    assert first == second
    assert first["entities"] > 0
    assert first["st_rule"] > 0
    assert first["data_type"] > 0
    assert first["compatibility"] > 0

    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            """
            SELECT entity_norm,chunk_id,task_types
            FROM entity_index
            WHERE manual_id='gxw2_skill_1_6_1' AND entity_type='skill_concept'
            ORDER BY entity_norm,chunk_id
            """
        ).fetchall()
        assert ("continue", 1, "st,generate,edit") in rows
        assert ("lreal", 2, "st,generate,edit,analysis") in rows
        assert ("fx3s", 3, "st,generate,analysis") in rows
        assert ("works3", 3, "st,generate,analysis") in rows

        # The derived routing layer must not mutate official structured evidence.
        official = connection.execute(
            "SELECT entity,entity_type FROM entity_index WHERE manual_id='official'"
        ).fetchall()
        assert official == [("MOV", "instruction")]

        assert connection.execute(
            "SELECT value FROM meta WHERE key='external_source_gxw2_skill_routing'"
        ).fetchone()[0] == "concept_entities_v1"
