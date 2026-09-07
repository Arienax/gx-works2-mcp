from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Literal

from .container import CompoundFile, ENDOFCHAIN, FREESECT
from .models import GXWFormatError


@dataclass(frozen=True)
class CFBStreamAllocation:
    name: str
    storage: Literal["mini", "regular"]
    stream_size: int
    allocation_capacity: int
    chain_length: int


def _regular_chain(cfb: CompoundFile, start_sector: int) -> list[int]:
    return CompoundFile._walk_chain(start_sector, cfb._fat)


def _mini_chain(cfb: CompoundFile, start_sector: int) -> list[int]:
    return CompoundFile._walk_chain(start_sector, cfb._minifat)


def inspect_stream_allocation(data: bytes, stream_name: str) -> CFBStreamAllocation:
    """Describe the existing allocation backing one unique CFB stream.

    This writer milestone deliberately does not allocate or free FAT/MiniFAT
    sectors. The returned capacity is therefore the hard upper bound for an
    in-place variable-size replacement.
    """

    cfb = CompoundFile(data)
    entry = cfb.get_stream_entry(stream_name)

    if entry.stream_size < cfb.mini_stream_cutoff:
        chain = _mini_chain(cfb, entry.start_sector) if entry.stream_size else []
        return CFBStreamAllocation(
            name=stream_name,
            storage="mini",
            stream_size=entry.stream_size,
            allocation_capacity=len(chain) * cfb.mini_sector_size,
            chain_length=len(chain),
        )

    chain = _regular_chain(cfb, entry.start_sector)
    return CFBStreamAllocation(
        name=stream_name,
        storage="regular",
        stream_size=entry.stream_size,
        allocation_capacity=len(chain) * cfb.sector_size,
        chain_length=len(chain),
    )


def _write_regular_chain_range(
    target: bytearray,
    *,
    cfb: CompoundFile,
    chain: list[int],
    logical_offset: int,
    payload: bytes,
) -> None:
    if logical_offset < 0:
        raise GXWFormatError("negative CFB logical write offset")
    capacity = len(chain) * cfb.sector_size
    if logical_offset + len(payload) > capacity:
        raise GXWFormatError(
            "CFB write exceeds the existing regular-sector chain capacity"
        )

    cursor = 0
    offset = logical_offset
    while cursor < len(payload):
        chain_index = offset // cfb.sector_size
        within_sector = offset % cfb.sector_size
        sector_id = chain[chain_index]
        physical_offset = (sector_id + 1) * cfb.sector_size + within_sector
        chunk_size = min(
            cfb.sector_size - within_sector,
            len(payload) - cursor,
        )
        target[physical_offset : physical_offset + chunk_size] = payload[
            cursor : cursor + chunk_size
        ]
        cursor += chunk_size
        offset += chunk_size


def _write_directory_stream_size(
    target: bytearray,
    *,
    cfb: CompoundFile,
    entry_index: int,
    stream_size: int,
) -> None:
    if stream_size < 0:
        raise GXWFormatError("negative CFB stream size")
    if cfb.major_version == 3 and stream_size > 0xFFFFFFFF:
        raise GXWFormatError("CFB v3 stream size exceeds uint32 range")

    directory_chain = _regular_chain(cfb, cfb.first_directory_sector)
    logical_offset = entry_index * 128 + 120
    _write_regular_chain_range(
        target,
        cfb=cfb,
        chain=directory_chain,
        logical_offset=logical_offset,
        payload=struct.pack("<Q", stream_size),
    )


def replace_stream_within_allocation(
    data: bytes,
    stream_name: str,
    new_data: bytes,
    *,
    allow_shrink: bool = False,
) -> bytes:
    """Replace a CFB stream without changing FAT/MiniFAT allocation.

    Supported operations stay within the stream's already allocated chain and
    must remain in the same CFB storage class (MiniStream vs regular FAT stream).
    This is sufficient for the first variable-length GXW write-back experiment:
    sample 48 grows Program.pou from 411 to 415 bytes, while both sizes still fit
    the same seven 64-byte mini-sectors.

    Sector allocation, storage-class transitions, chain growth and compaction are
    intentionally out of scope. The function fails closed when any is required.
    """

    cfb = CompoundFile(data)
    entry = cfb.get_stream_entry(stream_name)
    old_size = entry.stream_size
    new_size = len(new_data)

    if new_size < old_size and not allow_shrink:
        raise GXWFormatError(
            f"shrinking CFB stream {stream_name!r} is not enabled in this milestone"
        )

    old_is_mini = old_size < cfb.mini_stream_cutoff
    new_is_mini = new_size < cfb.mini_stream_cutoff
    if old_is_mini != new_is_mini:
        raise GXWFormatError(
            f"CFB stream {stream_name!r} would cross the MiniStream cutoff "
            f"({old_size} -> {new_size}); allocation rebuild is required"
        )

    target = bytearray(data)

    if old_is_mini:
        if old_size == 0 and new_size:
            raise GXWFormatError(
                f"CFB stream {stream_name!r} has no existing mini-sector allocation"
            )
        if not cfb._minifat and new_size:
            raise GXWFormatError(
                f"MiniFAT unavailable for CFB stream {stream_name!r}"
            )

        chain = _mini_chain(cfb, entry.start_sector) if old_size else []
        capacity = len(chain) * cfb.mini_sector_size
        if new_size > capacity:
            raise GXWFormatError(
                f"CFB stream {stream_name!r} needs {new_size} bytes but its existing "
                f"mini-sector allocation holds only {capacity} bytes"
            )

        root = cfb.root_entry
        if root.stream_size == 0 and new_size:
            raise GXWFormatError("CFB root MiniStream is empty")
        root_chain = _regular_chain(cfb, root.start_sector) if root.stream_size else []

        payload = new_data
        if new_size < old_size:
            payload += b"\x00" * (old_size - new_size)

        cursor = 0
        for mini_sector in chain:
            if cursor >= len(payload):
                break
            logical_offset = mini_sector * cfb.mini_sector_size
            chunk = payload[cursor : cursor + cfb.mini_sector_size]
            if logical_offset + len(chunk) > root.stream_size:
                raise GXWFormatError(
                    f"mini-sector {mini_sector} for {stream_name!r} is outside root MiniStream"
                )
            _write_regular_chain_range(
                target,
                cfb=cfb,
                chain=root_chain,
                logical_offset=logical_offset,
                payload=chunk,
            )
            cursor += len(chunk)
    else:
        chain = _regular_chain(cfb, entry.start_sector)
        capacity = len(chain) * cfb.sector_size
        if new_size > capacity:
            raise GXWFormatError(
                f"CFB stream {stream_name!r} needs {new_size} bytes but its existing "
                f"regular-sector allocation holds only {capacity} bytes"
            )

        payload = new_data
        if new_size < old_size:
            payload += b"\x00" * (old_size - new_size)
        _write_regular_chain_range(
            target,
            cfb=cfb,
            chain=chain,
            logical_offset=0,
            payload=payload,
        )

    _write_directory_stream_size(
        target,
        cfb=cfb,
        entry_index=entry.index,
        stream_size=new_size,
    )

    result = bytes(target)
    reparsed = CompoundFile(result)
    observed = reparsed.read_stream(stream_name)
    if observed != new_data:
        raise GXWFormatError(
            f"post-write verification failed for CFB stream {stream_name!r}"
        )
    if len(result) != len(data):
        raise GXWFormatError("within-allocation CFB replacement changed container length")

    return result
