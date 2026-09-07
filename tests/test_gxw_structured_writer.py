import base64
import json
from pathlib import Path
import struct

import pytest

from src.gxw.structured_pou import parse_structured_pou
from src.gxw.structured_pou_writer import (
    replace_node_symbol,
    serialize_structured_pou,
)


FIXTURES = Path(__file__).parent / "fixtures"


def _fixture_program(filename: str, sample: str) -> bytes:
    payload = json.loads((FIXTURES / filename).read_text(encoding="utf-8"))
    return base64.b64decode(payload[sample]["program_pou_base64"])


@pytest.mark.parametrize(
    ("filename", "sample"),
    [
        ("gxw_structured_52.json", "52"),
        ("gxw_structured_54_58.json", "54"),
        ("gxw_structured_54_58.json", "56"),
        ("gxw_structured_54_58.json", "57"),
        ("gxw_structured_54_58.json", "58"),
        ("gxw_structured_67_71.json", "67"),
        ("gxw_structured_67_71.json", "71"),
        ("gxw_structured_72_75.json", "72"),
        ("gxw_structured_72_75.json", "74"),
        ("gxw_structured_72_75.json", "75"),
        ("gxw_structured_76.json", "76"),
        ("gxw_structured_77.json", "77"),
    ],
)
def test_structured_program_serializer_is_byte_perfect(filename, sample):
    raw = _fixture_program(filename, sample)
    program = parse_structured_pou(raw, logical_name="1.Program.pou")

    assert serialize_structured_pou(program) == raw


def test_variable_length_symbol_rebuild_updates_record_and_header_sizes():
    raw = _fixture_program("gxw_structured_52.json", "52")
    program = parse_structured_pou(raw, logical_name="1.Program.pou")
    original_first_record_length = program.nodes[0].record_length
    original_body_size = program.body_size

    modified = replace_node_symbol(program, "X1", "X100")
    rebuilt = serialize_structured_pou(modified)
    reparsed = parse_structured_pou(rebuilt, logical_name="1.Program.pou")

    assert len(rebuilt) == len(raw) + 4
    assert reparsed.nodes[0].symbol == "X100"
    assert reparsed.nodes[0].record_length == original_first_record_length + 4
    assert reparsed.nodes[1].offset == program.nodes[1].offset + 4
    assert reparsed.body_size == original_body_size + 4
    assert struct.unpack_from("<I", rebuilt, 0x37)[0] == reparsed.body_size + 12
    assert struct.unpack_from("<I", rebuilt, 0x3B)[0] == reparsed.body_size + 12
    assert struct.unpack_from("<I", rebuilt, 0x47)[0] == reparsed.body_size
    assert reparsed.record_count == program.record_count
    assert reparsed.canvas_height == program.canvas_height


def test_symbol_replacement_refuses_ambiguous_source_symbol():
    raw = _fixture_program("gxw_structured_52.json", "52")
    program = parse_structured_pou(raw, logical_name="1.Program.pou")

    # Create an intentionally ambiguous semantic copy without altering raw source.
    first = program.nodes[0]
    third = program.nodes[2]
    from dataclasses import replace

    ambiguous = replace(
        program,
        nodes=(first, program.nodes[1], replace(third, symbol="X1")),
    )

    with pytest.raises(ValueError, match="occurs in multiple nodes"):
        replace_node_symbol(ambiguous, "X1", "X100")
