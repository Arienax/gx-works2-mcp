from __future__ import annotations

from dataclasses import dataclass
import math
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


@dataclass(frozen=True)
class CFBRootMiniStreamAllocation:
    stream_size: int
    allocation_capacity: int
    regular_chain_length: int
    backed_mini_sectors: int
    max_backed_mini_sectors: int



def _regular_chain(cfb: CompoundFile, start_sector: int) -> list[int]:
    return CompoundFile._walk_chain(start_sector, cfb._fat)



def _mini_chain(cfb: CompoundFile, start_sector: int) -> list[int]:
    return CompoundFile._walk_chain(start_sector, cfb._minifat)



def inspect_stream_allocation(data: bytes, stream_name: str) -> CFBStreamAllocation:
    """Describe the allocation currently backing one unique CFB stream."""

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



def inspect_root_ministream_allocation(data: bytes) -> CFBRootMiniStreamAllocation:
    """Describe root MiniStream bytes already backed by its existing FAT chain."""

    cfb = CompoundFile(data)
    root = cfb.root_entry
    chain = _regular_chain(cfb, root.start_sector) if root.stream_size else []
    capacity = len(chain) * cfb.sector_size
    return CFBRootMiniStreamAllocation(
        stream_size=root.stream_size,
        allocation_capacity=capacity,
        regular_chain_length=len(chain),
        backed_mini_sectors=root.stream_size // cfb.mini_sector_size,
        max_backed_mini_sectors=min(
            capacity // cfb.mini_sector_size,
            len(cfb._minifat),
        ),
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



def _write_directory_field(
    target: bytearray,
    *,
    cfb: CompoundFile,
    entry_index: int,
    relative_offset: int,
    payload: bytes,
) -> None:
    directory_chain = _regular_chain(cfb, cfb.first_directory_sector)
    logical_offset = entry_index * 128 + relative_offset
    _write_regular_chain_range(
        target,
        cfb=cfb,
        chain=directory_chain,
        logical_offset=logical_offset,
        payload=payload,
    )



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
    _write_directory_field(
        target,
        cfb=cfb,
        entry_index=entry_index,
        relative_offset=120,
        payload=struct.pack("<Q", stream_size),
    )



def _write_minifat_entry(
    target: bytearray,
    *,
    cfb: CompoundFile,
    mini_sector: int,
    value: int,
) -> None:
    if mini_sector < 0 or mini_sector >= len(cfb._minifat):
        raise GXWFormatError(f"MiniFAT index {mini_sector} is outside the table")
    minifat_chain = _regular_chain(cfb, cfb.first_minifat_sector)
    if len(minifat_chain) < cfb.num_minifat_sectors:
        raise GXWFormatError("MiniFAT chain is shorter than the header declares")
    _write_regular_chain_range(
        target,
        cfb=cfb,
        chain=minifat_chain[: cfb.num_minifat_sectors],
        logical_offset=mini_sector * 4,
        payload=struct.pack("<I", value),
    )



def _write_mini_payload(
    target: bytearray,
    *,
    cfb: CompoundFile,
    chain: list[int],
    payload: bytes,
    root_stream_size_limit: int | None = None,
) -> None:
    root = cfb.root_entry
    limit = root.stream_size if root_stream_size_limit is None else root_stream_size_limit
    if limit == 0 and payload:
        raise GXWFormatError("CFB root MiniStream is empty")
    root_chain = _regular_chain(cfb, root.start_sector) if limit else []
    root_capacity = len(root_chain) * cfb.sector_size
    if limit > root_capacity:
        raise GXWFormatError(
            "requested root MiniStream size exceeds its existing regular-sector chain"
        )

    cursor = 0
    for mini_sector in chain:
        if cursor >= len(payload):
            break
        logical_offset = mini_sector * cfb.mini_sector_size
        chunk = payload[cursor : cursor + cfb.mini_sector_size]
        if logical_offset + len(chunk) > limit:
            raise GXWFormatError(
                f"mini-sector {mini_sector} is outside the permitted root MiniStream"
            )
        _write_regular_chain_range(
            target,
            cfb=cfb,
            chain=root_chain,
            logical_offset=logical_offset,
            payload=chunk,
        )
        cursor += len(chunk)

    if cursor != len(payload):
        raise GXWFormatError("mini-sector chain did not hold the requested payload")



def replace_stream_within_allocation(
    data: bytes,
    stream_name: str,
    new_data: bytes,
    *,
    allow_shrink: bool = False,
) -> bytes:
    """Replace a CFB stream without changing FAT/MiniFAT allocation."""

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

        payload = new_data
        if new_size < old_size:
            payload += b"\x00" * (old_size - new_size)
        _write_mini_payload(target, cfb=cfb, chain=chain, payload=payload)
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



def replace_stream_with_free_mini_growth(
    data: bytes,
    stream_name: str,
    new_data: bytes,
) -> bytes:
    """Grow a MiniStream-backed stream using only already-backed free mini-sectors."""

    cfb = CompoundFile(data)
    entry = cfb.get_stream_entry(stream_name)
    old_size = entry.stream_size
    new_size = len(new_data)

    if new_size <= old_size:
        return replace_stream_within_allocation(
            data,
            stream_name,
            new_data,
            allow_shrink=True,
        )
    if old_size == 0:
        raise GXWFormatError(
            f"CFB stream {stream_name!r} has no existing mini-sector chain to extend"
        )
    if old_size >= cfb.mini_stream_cutoff or new_size >= cfb.mini_stream_cutoff:
        raise GXWFormatError(
            f"CFB stream {stream_name!r} is not a supported MiniStream growth "
            f"({old_size} -> {new_size})"
        )
    if not cfb._minifat:
        raise GXWFormatError("MiniFAT unavailable for requested stream growth")

    chain = _mini_chain(cfb, entry.start_sector)
    required_chain_length = math.ceil(new_size / cfb.mini_sector_size)
    if required_chain_length <= len(chain):
        return replace_stream_within_allocation(data, stream_name, new_data)

    extra_needed = required_chain_length - len(chain)
    backed_mini_count = cfb.root_entry.stream_size // cfb.mini_sector_size
    backed_mini_count = min(backed_mini_count, len(cfb._minifat))
    free_backed = [
        index
        for index in range(backed_mini_count)
        if cfb._minifat[index] == FREESECT
    ]

    if len(free_backed) < extra_needed:
        raise GXWFormatError(
            f"CFB stream {stream_name!r} needs {extra_needed} additional mini-sectors, "
            f"but only {len(free_backed)} free backed mini-sectors are available; "
            "root MiniStream growth is required"
        )

    allocated = free_backed[:extra_needed]
    extended_chain = [*chain, *allocated]
    target = bytearray(data)

    _write_minifat_entry(
        target,
        cfb=cfb,
        mini_sector=chain[-1],
        value=allocated[0],
    )
    for index, mini_sector in enumerate(allocated):
        next_value = allocated[index + 1] if index + 1 < len(allocated) else ENDOFCHAIN
        _write_minifat_entry(
            target,
            cfb=cfb,
            mini_sector=mini_sector,
            value=next_value,
        )

    _write_mini_payload(
        target,
        cfb=cfb,
        chain=extended_chain,
        payload=new_data,
    )
    _write_directory_stream_size(
        target,
        cfb=cfb,
        entry_index=entry.index,
        stream_size=new_size,
    )

    result = bytes(target)
    if len(result) != len(data):
        raise GXWFormatError("free-mini-sector growth unexpectedly changed CFB length")

    reparsed = CompoundFile(result)
    observed = reparsed.read_stream(stream_name)
    if observed != new_data:
        raise GXWFormatError(
            f"post-growth verification failed for CFB stream {stream_name!r}"
        )
    grown = inspect_stream_allocation(result, stream_name)
    if grown.chain_length != required_chain_length:
        raise GXWFormatError(
            "post-growth MiniFAT chain length does not match requested stream size"
        )

    return result



def replace_stream_with_ministream_growth(
    data: bytes,
    stream_name: str,
    new_data: bytes,
) -> bytes:
    """Grow a MiniStream stream into free entries and existing root-FAT slack.

    Unlike :func:`replace_stream_with_free_mini_growth`, this milestone may enlarge
    the root MiniStream *directory size* when the root's existing regular FAT chain
    already contains enough unused trailing bytes. It still never allocates a new
    regular FAT sector and never changes the CFB file length.

    This is specifically useful for GXW sample 48: the nested `_hdb` reports no
    free mini-sectors inside the current logical root MiniStream, but its final FAT
    sector may still contain enough unexposed bytes to back the two additional
    64-byte mini-sectors needed by the first structural insertion experiment.
    """

    cfb = CompoundFile(data)
    entry = cfb.get_stream_entry(stream_name)
    old_size = entry.stream_size
    new_size = len(new_data)

    if new_size <= old_size:
        return replace_stream_within_allocation(
            data,
            stream_name,
            new_data,
            allow_shrink=True,
        )
    if old_size == 0:
        raise GXWFormatError(
            f"CFB stream {stream_name!r} has no existing mini-sector chain to extend"
        )
    if old_size >= cfb.mini_stream_cutoff or new_size >= cfb.mini_stream_cutoff:
        raise GXWFormatError(
            f"CFB stream {stream_name!r} is not a supported MiniStream growth "
            f"({old_size} -> {new_size})"
        )
    if not cfb._minifat:
        raise GXWFormatError("MiniFAT unavailable for requested stream growth")
    if cfb.root_entry.stream_size % cfb.mini_sector_size:
        raise GXWFormatError(
            "root MiniStream size is not aligned to the 64-byte mini-sector size"
        )

    chain = _mini_chain(cfb, entry.start_sector)
    required_chain_length = math.ceil(new_size / cfb.mini_sector_size)
    if required_chain_length <= len(chain):
        return replace_stream_within_allocation(data, stream_name, new_data)

    extra_needed = required_chain_length - len(chain)
    root = cfb.root_entry
    root_chain = _regular_chain(cfb, root.start_sector)
    root_capacity = len(root_chain) * cfb.sector_size
    current_backed = root.stream_size // cfb.mini_sector_size
    max_backed = min(
        root_capacity // cfb.mini_sector_size,
        len(cfb._minifat),
    )

    free_backed = [
        index
        for index in range(current_backed)
        if cfb._minifat[index] == FREESECT
    ]
    free_in_root_slack = [
        index
        for index in range(current_backed, max_backed)
        if cfb._minifat[index] == FREESECT
    ]
    candidates = [*free_backed, *free_in_root_slack]

    if len(candidates) < extra_needed:
        slack_bytes = max(0, root_capacity - root.stream_size)
        raise GXWFormatError(
            f"CFB stream {stream_name!r} needs {extra_needed} additional mini-sectors, "
            f"but only {len(candidates)} are available within the current root FAT "
            f"allocation ({slack_bytes} trailing bytes); root MiniStream FAT-chain "
            "growth is required"
        )

    allocated = candidates[:extra_needed]
    extended_chain = [*chain, *allocated]
    new_root_size = max(
        root.stream_size,
        (max(allocated) + 1) * cfb.mini_sector_size,
    )
    if new_root_size > root_capacity:
        raise GXWFormatError(
            "root MiniStream expansion would exceed its existing regular FAT allocation"
        )

    target = bytearray(data)

    # Newly exposed trailing bytes are zeroed before mini-sector payload is written.
    if new_root_size > root.stream_size:
        _write_regular_chain_range(
            target,
            cfb=cfb,
            chain=root_chain,
            logical_offset=root.stream_size,
            payload=b"\x00" * (new_root_size - root.stream_size),
        )

    _write_minifat_entry(
        target,
        cfb=cfb,
        mini_sector=chain[-1],
        value=allocated[0],
    )
    for index, mini_sector in enumerate(allocated):
        next_value = allocated[index + 1] if index + 1 < len(allocated) else ENDOFCHAIN
        _write_minifat_entry(
            target,
            cfb=cfb,
            mini_sector=mini_sector,
            value=next_value,
        )

    _write_mini_payload(
        target,
        cfb=cfb,
        chain=extended_chain,
        payload=new_data,
        root_stream_size_limit=new_root_size,
    )
    _write_directory_stream_size(
        target,
        cfb=cfb,
        entry_index=entry.index,
        stream_size=new_size,
    )
    if new_root_size != root.stream_size:
        _write_directory_stream_size(
            target,
            cfb=cfb,
            entry_index=root.index,
            stream_size=new_root_size,
        )

    result = bytes(target)
    if len(result) != len(data):
        raise GXWFormatError("MiniStream slack growth unexpectedly changed CFB length")

    reparsed = CompoundFile(result)
    if reparsed.read_stream(stream_name) != new_data:
        raise GXWFormatError(
            f"post-growth verification failed for CFB stream {stream_name!r}"
        )
    grown = inspect_stream_allocation(result, stream_name)
    if grown.chain_length != required_chain_length:
        raise GXWFormatError(
            "post-growth MiniFAT chain length does not match requested stream size"
        )
    if reparsed.root_entry.stream_size != new_root_size:
        raise GXWFormatError("post-growth root MiniStream size verification failed")

    return result
