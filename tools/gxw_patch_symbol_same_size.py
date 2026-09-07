from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

import olefile

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gxw.models import GXWFormatError
from gxw.project_resolver import GXWProjectResolver
from gxw.structured_pou import parse_structured_pou


def _logical_stream_name(resolver: GXWProjectResolver, logical_name: str) -> str:
    # Current resolver intentionally keeps this map private.
    # For this experimental tool we resolve through logical_files() rather than
    # hard-coding numeric stream IDs.
    for item in resolver.logical_files():
        if item.logical_name == logical_name:
            return item.stream_name
    raise KeyError(logical_name)


def _encode_symbol(symbol: str) -> bytes:
    # Program.pou stores UTF-16LE text followed by a terminating NUL code unit.
    return symbol.encode("utf-16le") + b"\x00\x00"


def _find_target_node(raw_pou: bytes, logical_name: str, old_symbol: str, node_index: int | None):
    program = parse_structured_pou(raw_pou, logical_name=logical_name)

    matches = [node for node in program.nodes if node.symbol == old_symbol]
    if node_index is not None:
        matches = [node for node in matches if node.offset == node_index]

    if not matches:
        raise GXWFormatError(
            f"no structured node with symbol {old_symbol!r}"
            + (f" at offset 0x{node_index:X}" if node_index is not None else "")
        )
    if len(matches) > 1:
        offsets = ", ".join(f"0x{node.offset:X}" for node in matches)
        raise GXWFormatError(
            f"symbol {old_symbol!r} occurs in multiple nodes ({offsets}); "
            "rerun with --node-offset 0x..."
        )
    return matches[0]


def _patch_node_symbol_same_size(
    raw_pou: bytes,
    *,
    logical_name: str,
    old_symbol: str,
    new_symbol: str,
    node_offset: int | None,
) -> bytes:
    old_bytes = _encode_symbol(old_symbol)
    new_bytes = _encode_symbol(new_symbol)

    if len(old_bytes) != len(new_bytes):
        raise GXWFormatError(
            "this tool only supports equal-length symbol replacement; "
            f"{old_symbol!r} encodes to {len(old_bytes)} bytes, "
            f"{new_symbol!r} encodes to {len(new_bytes)} bytes"
        )

    node = _find_target_node(raw_pou, logical_name, old_symbol, node_offset)

    # Ordinary and FB node records both store the first string at record offset 16:
    #   u32 record_length
    #   u32 record_class
    #   u32 node_kind
    #   u32 char_count
    #   UTF-16LE string...
    symbol_start = node.offset + 16
    symbol_end = symbol_start + len(old_bytes)

    actual = raw_pou[symbol_start:symbol_end]
    if actual != old_bytes:
        raise GXWFormatError(
            f"parser/raw mismatch at node 0x{node.offset:X}: "
            f"expected {old_bytes.hex(' ')}, got {actual.hex(' ')}"
        )

    patched = bytearray(raw_pou)
    patched[symbol_start:symbol_end] = new_bytes

    # Re-parse to ensure all existing structural invariants remain valid.
    reparsed = parse_structured_pou(bytes(patched), logical_name=logical_name)
    changed = [n for n in reparsed.nodes if n.offset == node.offset]
    if len(changed) != 1 or changed[0].symbol != new_symbol:
        raise GXWFormatError("post-patch parser verification failed")

    return bytes(patched)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Patch one Structured Ladder/FBD node symbol in a GXW file, "
            "restricted to equal-length replacements such as X1 -> X2."
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
        type=lambda s: int(s, 0),
        default=None,
        help="Exact Program.pou node offset, e.g. 0x103, if the symbol appears more than once.",
    )
    args = parser.parse_args()

    if args.gxw.resolve() == args.output.resolve():
        raise SystemExit("refusing to overwrite the source GXW; choose a different -o path")

    resolver = GXWProjectResolver.from_file(args.gxw)
    logical_name = resolver.choose_program_pou(args.program)
    stream_name = _logical_stream_name(resolver, logical_name)
    original_pou = resolver.read_logical_file(logical_name)

    patched_pou = _patch_node_symbol_same_size(
        original_pou,
        logical_name=logical_name,
        old_symbol=args.old_symbol,
        new_symbol=args.new_symbol,
        node_offset=args.node_offset,
    )

    if len(patched_pou) != len(original_pou):
        raise GXWFormatError("internal error: same-size patch changed Program.pou length")

    # Extract nested _hdb from the source.
    with olefile.OleFileIO(str(args.gxw)) as outer:
        hdb_bytes = outer.openstream("_hdb").read()

    with tempfile.TemporaryDirectory(prefix="gxw_patch_") as td:
        td = Path(td)
        hdb_path = td / "nested_hdb.cfb"
        hdb_path.write_bytes(hdb_bytes)

        # Equal-size in-place stream replacement inside nested CFB.
        with olefile.OleFileIO(str(hdb_path), write_mode=True) as hdb:
            if not hdb.exists(stream_name):
                raise GXWFormatError(
                    f"resolved nested stream {stream_name!r} does not exist"
                )
            existing = hdb.openstream(stream_name).read()
            if len(existing) != len(patched_pou):
                raise GXWFormatError(
                    "nested Program.pou stream size mismatch; refusing write"
                )
            hdb.write_stream(stream_name, patched_pou)

        new_hdb_bytes = hdb_path.read_bytes()
        if len(new_hdb_bytes) != len(hdb_bytes):
            raise GXWFormatError(
                "_hdb container size changed during equal-size patch; refusing outer write"
            )

        shutil.copy2(args.gxw, args.output)

        # Equal-size in-place stream replacement in the outer GXW CFB.
        with olefile.OleFileIO(str(args.output), write_mode=True) as outer_out:
            existing_hdb = outer_out.openstream("_hdb").read()
            if len(existing_hdb) != len(new_hdb_bytes):
                raise GXWFormatError(
                    "outer _hdb stream size mismatch; refusing write"
                )
            outer_out.write_stream("_hdb", new_hdb_bytes)

    # Final end-to-end validation using the project's own parser.
    check = GXWProjectResolver.from_file(args.output)
    check_name = check.choose_program_pou(logical_name)
    check_pou = check.read_logical_file(check_name)
    check_program = parse_structured_pou(check_pou, logical_name=check_name)

    hits = [n for n in check_program.nodes if n.symbol == args.new_symbol]
    if not hits:
        raise GXWFormatError(
            "output GXW reopened successfully but patched symbol was not found"
        )

    print("Patch completed.")
    print(f"Source:        {args.gxw}")
    print(f"Output:        {args.output}")
    print(f"Program:       {logical_name}")
    print(f"Nested stream: {stream_name}")
    print(f"Change:        {args.old_symbol} -> {args.new_symbol}")
    print("Parser check:  OK")
    print()
    print("Next manual test:")
    print("  1. Open the OUTPUT file in GX Works2.")
    print("  2. Confirm the node displays the new symbol.")
    print("  3. Compile/convert if applicable.")
    print("  4. Save, close, reopen, and confirm it remains valid.")


if __name__ == "__main__":
    main()
