from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gxw.container import CompoundFile
from gxw.container_writer import (
    inspect_stream_allocation,
    replace_stream_within_allocation,
)
from gxw.models import GXWFormatError
from gxw.project_resolver import GXWProjectResolver
from gxw.structured_pou import parse_structured_pou
from gxw.structured_pou_writer import (
    replace_node_symbol,
    serialize_structured_pou,
)


def _logical_stream_name(resolver: GXWProjectResolver, logical_name: str) -> str:
    for item in resolver.logical_files():
        if item.logical_name == logical_name:
            return item.stream_name
    raise KeyError(logical_name)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Patch one Structured Ladder/FBD node symbol in a GXW project. "
            "Variable-length edits are supported only when the rebuilt Program.pou "
            "still fits its existing CFB allocation."
        )
    )
    parser.add_argument("gxw", type=Path)
    parser.add_argument("old_symbol")
    parser.add_argument("new_symbol")
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument(
        "--program",
        default=None,
        help="Logical *.Program.pou name; required only when the project has multiple ones.",
    )
    parser.add_argument(
        "--node-offset",
        type=lambda value: int(value, 0),
        default=None,
        help="Exact source Program.pou node offset, e.g. 0x5F, if the symbol is ambiguous.",
    )
    args = parser.parse_args()

    source = args.gxw.resolve()
    output = args.output.resolve()
    if source == output:
        raise SystemExit("refusing to overwrite the source GXW; choose a different -o path")

    outer_bytes = args.gxw.read_bytes()
    outer = CompoundFile(outer_bytes, source=args.gxw)
    resolver = GXWProjectResolver(outer)

    logical_name = resolver.choose_program_pou(args.program)
    stream_name = _logical_stream_name(resolver, logical_name)
    original_pou = resolver.read_logical_file(logical_name)
    program = parse_structured_pou(
        original_pou,
        logical_name=logical_name,
        source_path=args.gxw,
    )

    modified_program = replace_node_symbol(
        program,
        args.old_symbol,
        args.new_symbol,
        node_offset=args.node_offset,
    )
    patched_pou = serialize_structured_pou(modified_program)

    hdb_bytes = outer.read_stream("_hdb")
    allocation = inspect_stream_allocation(hdb_bytes, stream_name)

    print("Program.pou rebuild:")
    print(f"  logical object: {logical_name}")
    print(f"  nested stream:  {stream_name}")
    print(f"  symbol:         {args.old_symbol} -> {args.new_symbol}")
    print(f"  size:           {len(original_pou)} -> {len(patched_pou)} bytes")
    print(
        f"  allocation:     {allocation.storage}, "
        f"{allocation.allocation_capacity} bytes capacity "
        f"({allocation.chain_length} sectors)"
    )

    if len(patched_pou) > allocation.allocation_capacity:
        raise GXWFormatError(
            "rebuilt Program.pou exceeds its existing CFB allocation; "
            "a FAT/MiniFAT allocation rebuild is required for this edit"
        )

    new_hdb_bytes = replace_stream_within_allocation(
        hdb_bytes,
        stream_name,
        patched_pou,
    )

    # The nested CFB writer above edits within existing allocation, so its file
    # length stays unchanged. Replacing the outer _hdb therefore remains a
    # same-size operation, also handled by the same conservative writer.
    if len(new_hdb_bytes) != len(hdb_bytes):
        raise GXWFormatError("nested _hdb container unexpectedly changed byte length")

    new_outer_bytes = replace_stream_within_allocation(
        outer_bytes,
        "_hdb",
        new_hdb_bytes,
    )

    # End-to-end in-memory verification before touching the output path.
    check_resolver = GXWProjectResolver(CompoundFile(new_outer_bytes, source=args.output))
    check_name = check_resolver.choose_program_pou(logical_name)
    check_pou = check_resolver.read_logical_file(check_name)
    check_program = parse_structured_pou(check_pou, logical_name=check_name)

    hits = [node for node in check_program.nodes if node.symbol == args.new_symbol]
    if not hits:
        raise GXWFormatError(
            "patched GXW reparsed successfully but the requested symbol was not found"
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(new_outer_bytes)

    print()
    print("Patch completed.")
    print(f"Source:       {args.gxw}")
    print(f"Output:       {args.output}")
    print("Parser check: OK")
    print()
    print("Manual GX Works2 validation:")
    print("  1. Open the OUTPUT copy.")
    print(f"  2. Confirm {args.new_symbol} is displayed at the target node.")
    print("  3. Convert/compile the program if applicable.")
    print("  4. Save, close, reopen, and verify the edit remains valid.")


if __name__ == "__main__":
    main()
