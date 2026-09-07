import base64
from dataclasses import replace
import json
from pathlib import Path
import struct

import pytest

from src.gxw.structured_pou import parse_structured_pou
from src.gxw.structured_pou_writer import (
    insert_series_contact_after,
    replace_node_symbol,
    serialize_structured_node,
    serialize_structured_pou,
    serialize_structured_wire,
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

    first = program.nodes[0]
    third = program.nodes[2]
    ambiguous = replace(
        program,
        nodes=(first, program.nodes[1], replace(third, symbol="X1")),
    )

    with pytest.raises(ValueError, match="occurs in multiple nodes"):
        replace_node_symbol(ambiguous, "X1", "X100")


def _simple_x1_y1_baseline_from_sample_51():
    """Derive a byte-valid X1 -> Y1 source using the controlled sample-51 ABI.

    Sample 51 is the GX Works2-produced reference for X1 -> M1 -> Y1. Removing
    the middle node and merging its two horizontal conductors gives the same
    five-record topology used by the simple sample-48 experiment while keeping
    all header noise and unknown wire fields grounded in a real GX Works2 sample.
    """

    raw = _fixture_program("gxw_structured_49_51.json", "51")
    series = parse_structured_pou(raw, logical_name="1.Program.pou")
    x1, middle, y1 = series.nodes
    rail, left_feed, x1_to_middle, middle_to_y1 = series.wires

    direct = replace(x1_to_middle, end=middle_to_y1.end)
    removed_bytes = len(serialize_structured_node(middle)) + len(
        serialize_structured_wire(middle_to_y1)
    )
    simple = replace(
        series,
        nodes=(x1, y1),
        wires=(rail, left_feed, direct),
        record_count=series.record_count - 2,
        body_size=series.body_size - removed_bytes,
    )
    rebuilt = serialize_structured_pou(simple)
    reparsed = parse_structured_pou(rebuilt, logical_name="1.Program.pou")

    assert len(rebuilt) == 411
    assert reparsed.record_count == 5
    assert [node.symbol for node in reparsed.nodes] == ["X1", "Y1"]
    assert [(wire.start.x, wire.start.y, wire.end.x, wire.end.y) for wire in reparsed.wires] == [
        (1, 0, 1, 5),
        (1, 2, 6, 2),
        (8, 2, 23, 2),
    ]
    return reparsed, series


def test_insert_series_contact_reproduces_known_sample_51_topology():
    simple, gxworks_series = _simple_x1_y1_baseline_from_sample_51()

    modified = insert_series_contact_after(simple, "X1", "X2")
    rebuilt = serialize_structured_pou(modified)
    reparsed = parse_structured_pou(rebuilt, logical_name="1.Program.pou")

    assert len(rebuilt) == 535
    assert reparsed.record_count == 7
    assert reparsed.body_size == 440
    assert [node.symbol for node in reparsed.nodes] == ["X1", "X2", "Y1"]
    assert [
        (node.bbox.left, node.bbox.top, node.bbox.right, node.bbox.bottom)
        for node in reparsed.nodes
    ] == [
        (6, 1, 8, 3),
        (11, 1, 13, 3),
        (23, 1, 25, 3),
    ]
    assert [
        (wire.start.x, wire.start.y, wire.end.x, wire.end.y)
        for wire in reparsed.wires
    ] == [
        (1, 0, 1, 5),
        (1, 2, 6, 2),
        (8, 2, 11, 2),
        (13, 2, 23, 2),
    ]

    # Stronger regression: the generated structure is byte-identical to the
    # GX Works2-created sample 51 after changing only M1 -> X2.
    expected = serialize_structured_pou(
        replace_node_symbol(gxworks_series, "M1", "X2")
    )
    assert rebuilt == expected


def test_insert_series_contact_shifts_a_tight_downstream_coil():
    simple, _ = _simple_x1_y1_baseline_from_sample_51()
    x1, y1 = simple.nodes
    rail, left_feed, direct = simple.wires

    # Model the tighter direct-rung layout seen in the real sample-48 project:
    # the downstream coil is too close for a contact at x=11..13. Moving the
    # coil and wire endpoint left keeps the binary ABI unchanged while exercising
    # the layout fallback.
    tight_y1 = replace(
        y1,
        bbox=replace(y1.bbox, left=9, right=11),
    )
    tight_direct = replace(direct, end=replace(direct.end, x=9))
    tight = replace(
        simple,
        nodes=(x1, tight_y1),
        wires=(rail, left_feed, tight_direct),
    )

    modified = insert_series_contact_after(tight, "X1", "X2")
    rebuilt = serialize_structured_pou(modified)
    reparsed = parse_structured_pou(rebuilt, logical_name="1.Program.pou")

    assert [node.symbol for node in reparsed.nodes] == ["X1", "X2", "Y1"]
    assert [
        (node.bbox.left, node.bbox.top, node.bbox.right, node.bbox.bottom)
        for node in reparsed.nodes
    ] == [
        (6, 1, 8, 3),
        (11, 1, 13, 3),
        (14, 1, 16, 3),
    ]
    assert [
        (wire.start.x, wire.start.y, wire.end.x, wire.end.y)
        for wire in reparsed.wires
    ] == [
        (1, 0, 1, 5),
        (1, 2, 6, 2),
        (8, 2, 11, 2),
        (13, 2, 14, 2),
    ]
