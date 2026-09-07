from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gxw.container import CompoundFile
from gxw.project_resolver import GXWProjectResolver


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _first_diff(a: bytes, b: bytes) -> int | None:
    for index, (left, right) in enumerate(zip(a, b)):
        if left != right:
            return index
    if len(a) != len(b):
        return min(len(a), len(b))
    return None


def _diff_count(a: bytes, b: bytes) -> int:
    shared = sum(left != right for left, right in zip(a, b))
    return shared + abs(len(a) - len(b))


def _logical_map(resolver: GXWProjectResolver) -> dict[str, str]:
    return {item.logical_name: item.stream_name for item in resolver.logical_files()}


def _stream_bytes(cfb: CompoundFile) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for entry in cfb.iter_streams():
        result[entry.name] = cfb.read_entry(entry)
    return result


def _fmt_diff(a: bytes | None, b: bytes | None) -> str:
    if a is None:
        return "BASE missing"
    if b is None:
        return "DONOR missing"
    if a == b:
        return "IDENTICAL"
    offset = _first_diff(a, b)
    return (
        f"CHANGED size {len(a)}->{len(b)}, bytes~{_diff_count(a, b)}, "
        f"first=0x{offset:X}, sha {_sha(a)}->{_sha(b)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Compare two GXW projects at logical-object, nested _hdb stream, and "
            "outer-stream levels. Intended for controlled reverse-engineering pairs."
        )
    )
    parser.add_argument("base", type=Path)
    parser.add_argument("donor", type=Path)
    parser.add_argument("--all", action="store_true", help="also print identical streams")
    args = parser.parse_args()

    base_outer = CompoundFile.from_file(args.base)
    donor_outer = CompoundFile.from_file(args.donor)
    base_resolver = GXWProjectResolver(base_outer)
    donor_resolver = GXWProjectResolver(donor_outer)

    base_logical = _logical_map(base_resolver)
    donor_logical = _logical_map(donor_resolver)

    print("GXW controlled-project comparison")
    print(f"BASE:  {args.base}")
    print(f"DONOR: {args.donor}")
    print()

    print("[1] Logical project objects")
    logical_changes: list[str] = []
    for name in sorted(set(base_logical) | set(donor_logical)):
        a = base_resolver.read_logical_file(name) if name in base_logical else None
        b = donor_resolver.read_logical_file(name) if name in donor_logical else None
        status = _fmt_diff(a, b)
        if status != "IDENTICAL":
            logical_changes.append(name)
        if args.all or status != "IDENTICAL":
            a_stream = base_logical.get(name, "-")
            b_stream = donor_logical.get(name, "-")
            print(f"  {name}  [{a_stream}->{b_stream}]  {status}")

    base_hdb = CompoundFile(base_outer.read_stream("_hdb"))
    donor_hdb = CompoundFile(donor_outer.read_stream("_hdb"))
    base_nested = _stream_bytes(base_hdb)
    donor_nested = _stream_bytes(donor_hdb)
    mapped_base = {stream: logical for logical, stream in base_logical.items()}
    mapped_donor = {stream: logical for logical, stream in donor_logical.items()}

    print()
    print("[2] Raw nested _hdb streams")
    raw_changes: list[str] = []
    for stream in sorted(set(base_nested) | set(donor_nested), key=lambda value: (0, int(value)) if value.isdigit() else (1, value)):
        a = base_nested.get(stream)
        b = donor_nested.get(stream)
        status = _fmt_diff(a, b)
        if status != "IDENTICAL":
            raw_changes.append(stream)
        if args.all or status != "IDENTICAL":
            logical = mapped_base.get(stream) or mapped_donor.get(stream) or "<unmapped>"
            print(f"  stream {stream:>6}  {logical:<32}  {status}")

    base_outer_streams = _stream_bytes(base_outer)
    donor_outer_streams = _stream_bytes(donor_outer)
    print()
    print("[3] Outer GXW streams")
    outer_changes: list[str] = []
    for stream in sorted(set(base_outer_streams) | set(donor_outer_streams)):
        a = base_outer_streams.get(stream)
        b = donor_outer_streams.get(stream)
        status = _fmt_diff(a, b)
        if status != "IDENTICAL":
            outer_changes.append(stream)
        if args.all or status != "IDENTICAL":
            print(f"  {stream:<32}  {status}")

    print()
    print("Summary")
    print(f"  changed logical objects: {len(logical_changes)}")
    print("    " + (", ".join(logical_changes) if logical_changes else "none"))
    print(f"  changed nested streams:  {len(raw_changes)}")
    print("    " + (", ".join(raw_changes) if raw_changes else "none"))
    print(f"  changed outer streams:   {len(outer_changes)}")
    print("    " + (", ".join(outer_changes) if outer_changes else "none"))
    print()
    print("Next isolation rule:")
    print("  Ignore 1.Program.pou first: its transplant was already tested.")
    print("  Prioritize changed logical or unmapped _hdb streams that differ between")
    print("  the native sample 48 and native sample 51. Transplant candidates one at a")
    print("  time into the sample-48 + donor-Program.pou hybrid until wires render.")


if __name__ == "__main__":
    main()
