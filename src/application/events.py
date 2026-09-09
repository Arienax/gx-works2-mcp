"""Durable, monotonically numbered job events."""

from __future__ import annotations

from datetime import datetime, timezone

from .workspace import public_payload


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_event(record: dict, event_type: str, data=None) -> dict:
    event = {
        "job_id": record["id"],
        "project_id": record.get("snapshot", {}).get("project_id"),
        "version_id": record.get("snapshot", {}).get("version_id") or record.get("snapshot", {}).get("base_version_id"),
        "sequence": int(record.get("last_sequence", 0)) + 1,
        "event_type": str(event_type)[:80],
        "created_at": utc_now(),
        "payload": public_payload(data or {}),
    }
    record.setdefault("events", []).append(event)
    record["last_sequence"] = event["sequence"]
    record["updated_at"] = event["created_at"]
    return event
