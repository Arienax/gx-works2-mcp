"""Lossless updates of observed GXW metadata (no XML reserialization)."""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import hashlib
from xml.parsers import expat

from .models import GXWFormatError


@dataclass
class XmlElement:
    name: str
    start: int
    content_start: int
    content_end: int = 0
    end: int = 0
    text: str = ""
    children: list = field(default_factory=list)

    def fields(self) -> dict:
        result = {}
        for child in self.children:
            if child.name in result:
                raise GXWFormatError(f"duplicate XML field {child.name}")
            result[child.name] = child
        return result


def xml_elements(raw: bytes) -> tuple[list[XmlElement], str]:
    """Return an XML tree with original byte spans, including UTF-16 input."""
    encoding = ("utf-16le" if raw.startswith((b"\xff\xfe", b"<\x00")) else
                "utf-16be" if raw.startswith((b"\xfe\xff", b"\x00<")) else "utf-8")
    parser = expat.ParserCreate(namespace_separator="}")
    roots, stack = [], []
    step = 2 if encoding.startswith("utf-16") else 1

    def tag_end(start):
        # Respect quoted '>' characters in attributes.
        quote = None
        for offset in range(start, len(raw), step):
            char = raw[offset:offset + step]
            if quote:
                if char == quote:
                    quote = None
            elif char in ('"'.encode(encoding), "'".encode(encoding)):
                quote = char
            elif char == ">".encode(encoding):
                return offset + step
        raise GXWFormatError("unterminated metadata tag")

    def start(name, attrs):
        pos = parser.CurrentByteIndex
        node = XmlElement(name.split("}")[-1], pos, tag_end(pos))
        (stack[-1].children if stack else roots).append(node)
        stack.append(node)

    def end(name):
        node = stack.pop()
        node.content_end = parser.CurrentByteIndex
        opening = raw[node.start:node.content_start].decode(encoding)
        node.end = node.content_start if opening.endswith("/>") else tag_end(node.content_end)

    def chars(value):
        if stack:
            stack[-1].text += value

    def reject(*args):
        raise GXWFormatError("DTD/entities are unsupported in GXW metadata")

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = chars
    parser.StartDoctypeDeclHandler = reject
    parser.ExternalEntityRefHandler = reject
    try:
        parser.Parse(raw, True)
    except (expat.ExpatError, UnicodeError) as exc:
        raise GXWFormatError(f"invalid or unsupported GXW XML: {exc}") from exc
    return roots, encoding


def current_rows(raw: bytes, dataset: str, row_name: str) -> tuple[list[XmlElement], str]:
    roots, encoding = xml_elements(raw)
    # Historical diffgr:before rows must never become current write targets.
    if len(roots) != 1:
        raise GXWFormatError("expected one metadata XML root")
    candidates = ([roots[0]] if roots[0].name == dataset else
                  [child for child in roots[0].children if child.name == dataset])
    if len(candidates) != 1:
        raise GXWFormatError(f"missing or ambiguous current dataset {dataset}")
    return [child for child in candidates[0].children if child.name == row_name], encoding


def logical_mapping(raw: bytes) -> dict[str, str]:
    rows, _ = current_rows(raw, "DSPROJECTDATA", "D_Projectdata")
    result = {}
    for row in rows:
        values = {k: v.text.strip() for k, v in row.fields().items()}
        scrap = values.get("bScrapFlag", "false").lower()
        if scrap in {"true", "1"}:
            continue
        if scrap not in {"false", "0"}:
            raise GXWFormatError("unsupported bScrapFlag")
        name, stream = values.get("szName"), values.get("iID")
        if not name or not stream:
            raise GXWFormatError("current project row lacks name/ID")
        if name in result or stream in result.values():
            raise GXWFormatError("ambiguous current project name/stream mapping")
        result[name] = stream
    return result


def md5_base64(raw: bytes) -> str:
    return base64.b64encode(hashlib.md5(raw).digest()).decode("ascii")


def synchronize_history(raw: bytes, replacements: dict) -> tuple[bytes, list, list]:
    """replacements: logical name -> (stream ID, old payload, new payload)."""
    rows, encoding = current_rows(raw, "DSHISTORY", "D_History")
    edits, changes, preserved = [], [], []
    for logical, (stream, old, new) in replacements.items():
        matches = []
        for row in rows:
            fields = row.fields()
            if fields.get("iProjectdataID") and fields["iProjectdataID"].text.strip() == stream:
                matches.append(fields)
        if len(matches) != 1:
            raise GXWFormatError(f"expected one current history row for {logical}; found {len(matches)}")
        fields = matches[0]
        if "szProjectdataName" not in fields or fields["szProjectdataName"].text.strip() != logical:
            raise GXWFormatError(f"history name/ID mismatch for {logical}")
        if "iFileSize" not in fields or not fields["iFileSize"].text.strip().isdigit():
            raise GXWFormatError(f"missing/invalid history iFileSize for {logical}")
        updates = {"iFileSize": str(len(new))}
        digest = fields.get("szMD5val")
        if digest and digest.text.strip() == md5_base64(old):
            updates["szMD5val"] = md5_base64(new)
        else:
            preserved.append({"object": logical, "field": "szMD5val", "status": "unknown",
                              "reason": "source digest absent or differs from Base64(MD5(payload)); preserved"})
        for field_name, value in updates.items():
            node = fields[field_name]
            if node.text.strip() == value:
                continue
            lexical = raw[node.content_start:node.content_end].decode(encoding)
            if node.children or lexical.strip() != node.text.strip():
                raise GXWFormatError(f"unsupported lexical representation of {field_name}")
            leading = lexical[:len(lexical) - len(lexical.lstrip())]
            trailing = lexical[len(lexical.rstrip()):]
            replacement = (leading + value + trailing).encode(encoding)
            edits.append((node.content_start, node.content_end, replacement))
            changes.append({"object": logical, "stream": stream, "field": field_name,
                            "before": node.text.strip(), "after": value,
                            "old_offset": node.content_start, "old_length": node.content_end - node.content_start,
                            "new_length": len(replacement), "offset_space": "history.xml bytes",
                            "status": "confirmed"})
    result = raw
    for start, end, payload in sorted(edits, reverse=True):
        result = result[:start] + payload + result[end:]
    shift = 0
    for change in sorted(changes, key=lambda c: c["old_offset"]):
        change["new_offset"] = change["old_offset"] + shift
        shift += change["new_length"] - change["old_length"]
    current_rows(result, "DSHISTORY", "D_History")
    return result, changes, preserved
