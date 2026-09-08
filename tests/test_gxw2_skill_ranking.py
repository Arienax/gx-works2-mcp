from pathlib import Path
import json
import sqlite3

import pytest
from tools import tune_gxw2_skill_ranking as tuner
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
                plc_models TEXT NOT NULL,
                entities TEXT NOT NULL DEFAULT '',
                entities_json TEXT
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
            CREATE VIRTUAL TABLE chunks_fts USING fts5(
                text,
                entities,
                content='chunks',
                content_rowid='id',
                tokenize='unicode61 remove_diacritics 0'
            );
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
            "INSERT INTO chunks(id,manual_id,chunk_type,text,plc_models,entities) VALUES(?,?,?,?,?,?)",
            [
                (
                    1,
                    "gxw2_skill_1_6_1",
                    "st_rule",
                    "No CONTINUE. Comment Style uses block comments. VAR_IN_OUT is unsupported. 3-Program Structure uses PRG_MAIN. FB instances are declared separately.",
                    "FX3U,FX3G,FX3S",
                    "",
                ),
                (
                    2,
                    "gxw2_skill_1_6_1",
                    "data_type",
                    "Unsupported Types include LREAL and WSTRING. Memory Consumption: DINT DWORD REAL.",
                    "FX3U,FX3G,FX3S",
                    "",
                ),
                (
                    3,
                    "gxw2_skill_1_6_1",
                    "compatibility",
                    "Feature Matrix STRING. Device Ranges FX3S. GX Works 2 vs GX Works 3.",
                    "FX3U,FX3G,FX3S",
                    "",
                ),
                (
                    4,
                    "official",
                    "instruction",
                    "CONTINUE STRING FX3S GX Works 3",
                    "FX3U",
                    "MOV",
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
        connection.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
        connection.commit()


def test_tune_database_adds_scoped_supporting_concepts_and_is_idempotent(tmp_path):
    database = tmp_path / "knowledge.sqlite"
    _create_database(database)

    first = tune_database(database)
    second = tune_database(database)

    assert first == second
    assert first["entities"] > 0
    assert first["fts_chunks"] == 3
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
        assert ("gxw2_program_structure", 1, "st,generate,edit") in rows
        assert ("lreal", 2, "st,generate,edit,analysis") in rows
        assert ("fx3s", 3, "st,generate,analysis") in rows
        assert ("works3", 3, "st,generate,analysis") in rows

        # Derived concepts are also mirrored into the FTS lexical metadata.
        st_entities = connection.execute(
            "SELECT entities FROM chunks WHERE id=1"
        ).fetchone()[0]
        assert "CONTINUE" in st_entities.split()
        assert "PROGRAM" not in st_entities.split()
        assert "GXW2_PROGRAM_STRUCTURE" not in st_entities.split()
        assert not any(row[0] == "program" for row in rows)

        # The derived routing layer must not mutate official structured evidence.
        official = connection.execute(
            "SELECT entity,entity_type FROM entity_index WHERE manual_id='official'"
        ).fetchall()
        assert official == [("MOV", "instruction")]
        assert connection.execute(
            "SELECT entities FROM chunks WHERE id=4"
        ).fetchone()[0] == "MOV"

        assert connection.execute(
            "SELECT value FROM meta WHERE key='external_source_gxw2_skill_routing'"
        ).fetchone()[0] == "scoped_concepts_native_entities_v3"


def test_tuner_removes_legacy_orphan_tokens_and_preserves_native_snapshot(tmp_path, monkeypatch):
    database = tmp_path / "knowledge.sqlite"
    _create_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE chunks SET entities=?, entities_json=? WHERE id=1",
            ("PROGRAM TEXT COMMENT REMOVED_CONCEPT RS", json.dumps([
                {"entity": "RS", "type": "instruction", "occurrences": 1},
            ])),
        )
        original = connection.execute("SELECT id,text,entities_json FROM chunks ORDER BY id").fetchall()
    tune_database(database)
    # Even after every route is removed, no derived tokens survive in any
    # formerly routed chunk, including tokens with no old entity_index row.
    monkeypatch.setattr(tuner, "CONCEPT_ROUTES", {})
    tune_database(database)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT entities FROM chunks WHERE id=1").fetchone()[0] == "RS"
        assert connection.execute("SELECT entities FROM chunks WHERE id IN (2,3)").fetchall() == [("",), ("",)]
        assert connection.execute("SELECT COUNT(*) FROM entity_index WHERE entity_type='skill_concept'").fetchone()[0] == 0
        assert connection.execute("SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH 'REMOVED_CONCEPT'").fetchall() == []
        assert connection.execute("SELECT id,text,entities_json FROM chunks ORDER BY id").fetchall() == original
        first_rows = connection.execute("SELECT id,entities FROM chunks ORDER BY id").fetchall()
    tune_database(database)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT id,entities FROM chunks ORDER BY id").fetchall() == first_rows


def test_legacy_schema_cleanup_preserves_native_collision_and_removed_route(tmp_path, monkeypatch):
    database = tmp_path / "knowledge.sqlite"
    _create_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE chunks SET entities='PROGRAM RS KEEP' WHERE id=1")
        connection.execute("INSERT INTO entity_index VALUES('rs','RS','instruction','FX3U','*','gxw2_skill_1_6_1',1,1)")
    tune_database(database)
    monkeypatch.setattr(tuner, "CONCEPT_ROUTES", {})
    tune_database(database)
    with sqlite3.connect(database) as connection:
        assert set(connection.execute("SELECT entities FROM chunks WHERE id=1").fetchone()[0].split()) == {"RS", "KEEP"}


def test_tuner_refuses_official_source(tmp_path):
    database = tmp_path / "knowledge.sqlite"
    _create_database(database)
    before = database.read_bytes()
    with pytest.raises(RuntimeError, match="non-third-party"):
        tune_database(database, "official")
    assert database.read_bytes() == before
