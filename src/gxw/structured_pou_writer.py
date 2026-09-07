from __future__ import annotations

from dataclasses import replace
import struct
from typing import Optional

from .models import (
    GXWFormatError,
    StructuredNode,
    StructuredProgram,
    StructuredWire,
    UnknownRecord,
)
from .structured_pou import (
    BODY_SIZE_OFFSET,
    CANVAS_HEIGHT_OFFSET,
    RECORD_COUNT_OFFSET,
    STRUCTURED_RECORDS_OFFSET,
    parse_structured_pou,
)


SIZE_LIKE_A_OFFSET = 0x37
SIZE_LIKE_B_OFFSET = 0x3B


def _u32(data: bytes, offset: int) -> int:
    if offset + 4 > len(data):
        raise GXWFormatError(f"truncated uint32 at 0x{offset:X}")
    return struct.unpack_from("<I", data, offset)[0]


def _serialize_node_string(value: str, *, field_name: str) -> bytes:
    if "\x00" in value:
        raise GXWFormatError(f"embedded NUL is unsupported in structured-node {field_name}")
    encoded = (value + "\x00").encode("utf-16le")
    char_count = len(encoded) // 2
    return struct.pack("<I", char_count) + encoded


def serialize_structured_node(node: StructuredNode) -> bytes:
    """Serialize one verified Structured Ladder/FBD node record.

    The implementation intentionally covers only layouts already accepted by the
    strict parser: ordinary nodes and the observed kind-0x02 function-block ABI.
    Record length is recomputed from the serialized fields rather than copied from
    ``node.record_length`` so variable-length symbol edits are supported.
    """

    body = bytearray()
    body.extend(struct.pack("<II", 1, node.kind_code))
    body.extend(_serialize_node_string(node.symbol, field_name="symbol"))

    if node.kind_code == 0x02:
        if node.type_name is None:
            raise GXWFormatError("function-block node is missing its serialized type name")
        if node.object_flag is not None or node.reserved is not None:
            raise GXWFormatError(
                "function-block node unexpectedly contains ordinary-node flag fields"
            )
        body.extend(_serialize_node_string(node.type_name, field_name="FB type"))
    else:
        if node.object_flag is None or node.reserved is None:
            raise GXWFormatError(
                f"ordinary node kind 0x{node.kind_code:02X} is missing flag/reserved fields"
            )
        body.extend(struct.pack("<IH", node.object_flag, node.reserved))

    body.extend(
        struct.pack(
            "<IIII",
            node.bbox.left,
            node.bbox.top,
            node.bbox.right,
            node.bbox.bottom,
        )
    )
    body.extend(struct.pack("<I", len(node.ports)))

    for port in node.ports:
        if port.size != 16:
            raise GXWFormatError(
                f"cannot serialize unsupported structured port size {port.size}"
            )
        body.extend(
            struct.pack(
                "<IIII",
                port.size,
                port.port_kind_code,
                port.local_x,
                port.local_y,
            )
        )

    record_length = 4 + len(body)
    return struct.pack("<I", record_length) + bytes(body)


def serialize_structured_wire(wire: StructuredWire) -> bytes:
    """Serialize one observed 44-byte wire record."""

    if wire.record_length != 44:
        raise GXWFormatError(
            f"cannot serialize unsupported structured wire length {wire.record_length}"
        )

    unknown0, unknown1, unknown2, unknown3, unknown4 = wire.prefix_fields
    return struct.pack(
        "<IIIIHHIIIIII",
        44,
        2,
        unknown0,
        unknown1,
        unknown2,
        unknown3,
        unknown4,
        wire.start.x,
        wire.start.y,
        wire.end.x,
        wire.end.y,
        wire.suffix,
    )


def _validate_source_header(program: StructuredProgram) -> None:
    raw = program.raw
    if len(raw) < STRUCTURED_RECORDS_OFFSET:
        raise GXWFormatError("StructuredProgram raw source is shorter than its header")

    if _u32(raw, BODY_SIZE_OFFSET) != program.body_size:
        raise GXWFormatError("StructuredProgram body_size no longer matches its raw source")
    if _u32(raw, CANVAS_HEIGHT_OFFSET) != program.canvas_height:
        raise GXWFormatError(
            "StructuredProgram canvas_height no longer matches its raw source"
        )
    if _u32(raw, RECORD_COUNT_OFFSET) != program.record_count:
        raise GXWFormatError("StructuredProgram record_count no longer matches its raw source")

    # This relation is strongly repeated across the controlled Structured
    # Ladder/FBD corpus. The writer intentionally fails closed rather than
    # inventing values for a project variant where the invariant does not hold.
    expected_size_like = program.body_size + 12
    for offset in (SIZE_LIKE_A_OFFSET, SIZE_LIKE_B_OFFSET):
        actual = _u32(raw, offset)
        if actual != expected_size_like:
            raise GXWFormatError(
                "unsupported Structured Program header invariant: "
                f"0x{offset:X}=0x{actual:X}, expected body_size+12 "
                f"(0x{expected_size_like:X})"
            )


def serialize_structured_pou(
    program: StructuredProgram,
    *,
    verify: bool = True,
) -> bytes:
    """Serialize the currently verified Structured Ladder/FBD Program.pou model.

    Unknown record classes are preserved byte-for-byte. Known node and wire records
    are rebuilt from parsed fields. The original header is retained except for the
    verified size/count/height fields that must follow the rebuilt body.

    With an unmodified parsed program this function is expected to produce a
    byte-perfect round trip for the controlled corpus.
    """

    _validate_source_header(program)

    serialized_records: list[bytes] = []
    for record in program.iter_records():
        if isinstance(record, StructuredNode):
            serialized_records.append(serialize_structured_node(record))
        elif isinstance(record, StructuredWire):
            serialized_records.append(serialize_structured_wire(record))
        elif isinstance(record, UnknownRecord):
            serialized_records.append(record.raw)
        else:
            raise GXWFormatError(
                f"unsupported Structured Program record object: {type(record).__name__}"
            )

    if len(program.trailer) != 24 or any(program.trailer):
        raise GXWFormatError("writer only supports the observed 24-zero-byte trailer")

    body = b"".join(serialized_records) + program.trailer
    body_size = len(body)

    header = bytearray(program.raw[:STRUCTURED_RECORDS_OFFSET])
    struct.pack_into("<I", header, SIZE_LIKE_A_OFFSET, body_size + 12)
    struct.pack_into("<I", header, SIZE_LIKE_B_OFFSET, body_size + 12)
    struct.pack_into("<I", header, BODY_SIZE_OFFSET, body_size)
    struct.pack_into("<I", header, CANVAS_HEIGHT_OFFSET, program.canvas_height)
    struct.pack_into("<I", header, RECORD_COUNT_OFFSET, len(serialized_records))

    result = bytes(header) + body

    if verify:
        reparsed = parse_structured_pou(
            result,
            logical_name=program.logical_name,
            source_path=program.source_path,
        )
        if reparsed.record_count != len(serialized_records):
            raise GXWFormatError("serialized Program.pou failed record-count verification")

    return result


def replace_node_symbol(
    program: StructuredProgram,
    old_symbol: str,
    new_symbol: str,
    *,
    node_offset: Optional[int] = None,
) -> StructuredProgram:
    """Return a copy with exactly one parsed node symbol replaced.

    ``node_offset`` refers to the node offset in the source Program.pou and is only
    needed when the same symbol occurs in multiple nodes.
    """

    matches = [
        (index, node)
        for index, node in enumerate(program.nodes)
        if node.symbol == old_symbol
        and (node_offset is None or node.offset == node_offset)
    ]

    if not matches:
        suffix = f" at offset 0x{node_offset:X}" if node_offset is not None else ""
        raise GXWFormatError(f"no structured node with symbol {old_symbol!r}{suffix}")

    if len(matches) > 1:
        offsets = ", ".join(f"0x{node.offset:X}" for _, node in matches)
        raise GXWFormatError(
            f"symbol {old_symbol!r} occurs in multiple nodes ({offsets}); "
            "specify node_offset"
        )

    index, node = matches[0]
    nodes = list(program.nodes)
    nodes[index] = replace(node, symbol=new_symbol)
    return replace(program, nodes=tuple(nodes))
