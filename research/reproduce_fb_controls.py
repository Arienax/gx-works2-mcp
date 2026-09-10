"""Reproduce the 2026-09-10 controlled POU edits; GX compilation stays external.

Inputs are retained, hash-addressed experiments described in docs/research.
The supplied local-label baseline must have been edited/saved by GX Works2.
Coordinates here define the experiment, never allocator/rendering thresholds.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from gxw.decoder import read_structured_program
from gxw.fb_connectivity import fb_connectivity_model
from gxw.models import GXWFormatError, NodeKind, Point
from gxw.project_writer import write_gxw_project, write_new_file


def make_control(mode, model, wire_template=None):
    if mode == "rename":
        names = {"timer_a": "TON_A", "timer_b": "TON_B"}
        blocks = [n for n in model.nodes if n.kind == NodeKind.FUNCTION_BLOCK]
        if len(blocks) != 2 or {n.symbol for n in blocks} != set(names) or any(n.type_name != "TON" for n in blocks):
            raise GXWFormatError("rename control needs the two TON instances from sample 76")
        return replace(model, nodes=tuple(replace(n, symbol=names.get(n.symbol, n.symbol)) for n in model.nodes))
    if mode == "type":
        hits = [n for n in model.nodes if n.instance_name == "TON_A" and n.type_name == "TON"]
        if len(hits) != 1:
            raise GXWFormatError("type control needs one declared TON_A: TON")
        return replace(model, nodes=tuple(replace(n, type_name="TOF") if n is hits[0] else n for n in model.nodes))
    positions = {"TON_A": (8, 2), "X1": (6, 3), "T#1s": (6, 4), "elapsed_a": (13, 4),
                 "TON_B": (21, 2), "Y2": (26, 3), "T#2s": (19, 4), "elapsed_b": (26, 4)}
    if len(model.nodes) != 10 or {n.symbol for n in model.nodes} != set(positions) | {"Y1", "X2"}:
        raise GXWFormatError("connect control needs the documented two-TON baseline")
    if wire_template is None or model.unknown_records:
        raise GXWFormatError("connect control requires a parsed wire template and modeled records")
    nodes = []
    for node in model.nodes:
        if node.symbol not in positions:
            continue
        left, top = positions[node.symbol]
        b = node.bbox
        nodes.append(replace(node, bbox=replace(b, left=left, top=top,
                             right=left + b.right - b.left, bottom=top + b.bottom - b.top)))
    wire = replace(wire_template, offset=max(r.offset for r in model.iter_records()) + 1,
                   start=Point(13, 4), end=Point(21, 4))
    result = replace(model, nodes=tuple(nodes), wires=(*model.wires, wire))
    relationship = fb_connectivity_model(result)["nets"]
    if len(relationship) != 1 or relationship[0]["sources"][0]["formal"] != "Q" or relationship[0]["sinks"][0]["formal"] != "IN":
        raise GXWFormatError("control does not yield the expected Q -> IN relationship")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["rename", "type", "connect"])
    parser.add_argument("baseline", type=Path)
    parser.add_argument("--wire-template", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists() or args.report.resolve() in {args.output.resolve(), args.baseline.resolve()}:
        parser.error("report must be a distinct new file")
    template = read_structured_program(args.wire_template).wires[0] if args.wire_template else None
    model = make_control(args.mode, read_structured_program(args.baseline), template)
    result = write_gxw_project(args.baseline, args.output, model)
    write_new_file(args.report, json.dumps(result.report, ensure_ascii=False, indent=2).encode())


if __name__ == "__main__":
    main()
