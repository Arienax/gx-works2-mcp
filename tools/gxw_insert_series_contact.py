from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gxw.container import CompoundFile, FREESECT
from gxw.container_writer import (
    inspect_root_ministream_allocation,
    inspect_stream_allocation,
    replace_stream_with_ministream_growth,
    replace_stream_within_allocation,
)
from gxw.models import GXWFormatError
from gxw.project_resolver import GXWProjectResolver
from gxw.structured_pou import parse_structured_pou
from gxw.structured_pou_writer import (
    insert_series_contact_after,
    serialize_structured_pou,
)


def _logical_stream_name(resolver: GXWProjectResolver, logical_name: str) -> str:
    for item in resolver.logical_files():
        if item.logical_name == logical_name:
            return item.stream_name
    raise KeyError(logical_name)


def _free_backed_mini_sectors(data: bytes) -> tuple[int, int]:
    cfb = CompoundFile(data)
    if not cfb._minifat or not cfb.root_entry.stream_size:
        return (0, 0)
    backed = min(
        cfb.root_entry.stream_size // cfb.mini_sector_size,
        len(cfb._minifat),
    )
    free = sum(1 for index in range(backed) if cfb._minifat[index] == FREESECT)
    return backed, free


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Experimental Structured Ladder/FBD structure edit: insert one "
            "normally-open contact in series after an existing contact. The first "
            "controlled target is sample 48: X1 -> Y1 becomes X1 -> X2 -> Y1."
        )
    )
    parser.add_argument("gxw", type=Path)
    parser.add_argument("after_symbol", help="Existing normally-open contact, e.g. X1")
    parser.add_argument("new_symbol", help="New contact symbol, e.g. X2")
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
        help="Exact source Program.pou node offset if after_symbol is ambiguous.",
    )
    parser.add_argument(
        "--gap",
        type=int,
        default=3,
        help="Horizontal grid gap between source and inserted contact; default 3.",
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

    modified = insert_series_contact_after(
        program,
        args.after_symbol,
        args.new_symbol,
        node_offset=args.node_offset,
        horizontal_gap=args.gap,
    )
    patched_pou = serialize_structured_pou(modified)

    hdb_bytes = outer.read_stream("_hdb")
    before = inspect_stream_allocation(hdb_bytes, stream_name)
    root_before = inspect_root_ministream_allocation(hdb_bytes)
    backed, free_backed = _free_backed_mini_sectors(hdb_bytes)

    print("Structured Program insertion:")
    print(f"  logical object:  {logical_name}")
    print(f"  nested stream:   {stream_name}")
    print(f"  edit:             insert {args.new_symbol} after {args.after_symbol}")
    print(f"  records:          {program.record_count} -> {modified.record_count}")
    print(f"  size:             {len(original_pou)} -> {len(patched_pou)} bytes")
    print(
        f"  allocation:       {before.storage}, {before.allocation_capacity} bytes "
        f"({before.chain_length} sectors)"
    )
    if before.storage == "mini":
        print(
            f"  root MiniStream:  {root_before.stream_size} bytes logical / "
            f"{root_before.allocation_capacity} bytes FAT capacity"
        )
        print(
            f"  mini-sector map:  {backed} backed, {free_backed} free-backed, "
            f"{root_before.max_backed_mini_sectors - backed} more can be exposed "
            "without FAT growth"
        )

    if len(patched_pou) <= before.allocation_capacity:
        new_hdb_bytes = replace_stream_within_allocation(
            hdb_bytes,
            stream_name,
            patched_pou,
        )
        allocation_mode = "existing chain"
    else:
        new_hdb_bytes = replace_stream_with_ministream_growth(
            hdb_bytes,
            stream_name,
            patched_pou,
        )
        root_after_growth = inspect_root_ministream_allocation(new_hdb_bytes)
        if root_after_growth.stream_size > root_before.stream_size:
            allocation_mode = "extended MiniFAT chain + exposed existing root FAT slack"
        else:
            allocation_mode = "extended MiniFAT chain using free backed mini-sectors"

    after = inspect_stream_allocation(new_hdb_bytes, stream_name)
    root_after = inspect_root_ministream_allocation(new_hdb_bytes)
    print(
        f"  result allocation: {after.allocation_capacity} bytes "
        f"({after.chain_length} sectors; {allocation_mode})"
    )
    if root_after.stream_size != root_before.stream_size:
        print(
            f"  root MiniStream:  {root_before.stream_size} -> "
            f"{root_after.stream_size} bytes (container length unchanged)"
        )

    # This milestone may enlarge the logical root MiniStream only inside bytes
    # already covered by its regular FAT chain. The nested CFB file itself stays
    # byte-for-byte the same length, so the outer _hdb stream still needs no FAT
    # growth.
    if len(new_hdb_bytes) != len(hdb_bytes):
        raise GXWFormatError(
            "nested _hdb container changed length; outer CFB growth is not enabled"
        )

    new_outer_bytes = replace_stream_within_allocation(
        outer_bytes,
        "_hdb",
        new_hdb_bytes,
    )

    # End-to-end parser verification before writing the output file.
    check_resolver = GXWProjectResolver(CompoundFile(new_outer_bytes, source=args.output))
    check_name = check_resolver.choose_program_pou(logical_name)
    check_pou = check_resolver.read_logical_file(check_name)
    check_program = parse_structured_pou(check_pou, logical_name=check_name)

    if check_program.record_count != program.record_count + 2:
        raise GXWFormatError(
            "patched GXW reparsed but record_count did not increase by two"
        )
    inserted = [node for node in check_program.nodes if node.symbol == args.new_symbol]
    if len(inserted) != 1:
        raise GXWFormatError(
            "patched GXW reparsed but the inserted contact was not found exactly once"
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(new_outer_bytes)

    print()
    print("Structure patch completed.")
    print(f"Source:       {args.gxw}")
    print(f"Output:       {args.output}")
    print("Parser check: OK")
    print()
    print("Manual GX Works2 validation:")
    print("  1. Open the OUTPUT copy.")
    print(
        f"  2. Confirm the rung displays {args.after_symbol} -> "
        f"{args.new_symbol} -> Y1 (for sample 48)."
    )
    print("  3. Convert/compile the program if applicable.")
    print("  4. Save, close, reopen, and verify the inserted contact remains valid.")


if __name__ == "__main__":
    main()
