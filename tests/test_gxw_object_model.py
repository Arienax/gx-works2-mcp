from copy import deepcopy
from dataclasses import replace
import json
import xml.etree.ElementTree as ET

import pytest

from src.gxw.models import GXWFormatError, NodeKind
from src.gxw.object_model import (build_object_program, catalog_description, default_baseline,
    export_object_model, generate_object_project, read_project)
from src.gxw.ladder_lowering import ladder_to_object_model
from src.gxw.render import render_structured_svg
from src.gxw.fb_connectivity import fb_connectivity_model
from tests.test_gxw_declarations import baseline


@pytest.mark.parametrize("case", ["s", "fn", "f2", "t2c"])
def test_import_and_unchanged_object_export_preserve_every_project_byte(case):
    raw = baseline(case)
    p, labels, _ = read_project(raw)
    model = export_object_model(p, labels)
    assert generate_object_project(model, baseline=raw).data == raw
    ET.fromstring(render_structured_svg(p))


def two_timers():
    return {"schema_version": 1, "program": "1.Program.pou", "canvas_height": 10,
            "nodes": [
                {"id": "a", "template": "function_block:TON", "symbol": "TIMER_A", "x": 8, "y": 2},
                {"id": "b", "template": "function_block:TON", "symbol": "TIMER_B", "x": 21, "y": 2},
                {"id": "x", "template": "input", "symbol": "X0", "x": 6, "y": 3},
                {"id": "pt1", "template": "input", "symbol": "T#1s", "x": 6, "y": 4},
                {"id": "pt2", "template": "input", "symbol": "T#2s", "x": 19, "y": 4},
                {"id": "out", "template": "output", "symbol": "Y0", "x": 26, "y": 3},
            ], "wires": [{"start": [1, 0], "end": [1, 10]}, {"from": "a.Q", "to": "b.IN"}]}


def test_named_port_link_creates_native_wire_and_local_fb_bindings():
    result = generate_object_project(two_timers())
    p, labels, _ = read_project(result.data)
    net, = fb_connectivity_model(p)["nets"]
    assert net["connection"] == "wire_network"
    assert (net["sources"][0]["instance"], net["sinks"][0]["instance"]) == ("TIMER_A", "TIMER_B")
    assert [(r.name, r.type_reference) for r in labels['1.Labels.lh'].rows] == [("TIMER_A", "TON"), ("TIMER_B", "TON")]


@pytest.mark.parametrize("damage", ["node_id", "offset", "template", "port", "diagonal", "dimensions"])
def test_invalid_models_fail_explicitly(damage):
    model = two_timers()
    if damage == "node_id": model["nodes"][1]["id"] = "a"
    if damage == "offset": model["nodes"][0]["source_offset"] = 99999
    if damage == "template": model["nodes"][0]["template"] = "function_block:UNKNOWN"
    if damage == "port": model["wires"][1]["from"] = "a.FAKE"
    if damage == "diagonal": model["nodes"][1]["y"] += 1
    if damage == "dimensions": model["nodes"][0]["width"] = 100
    with pytest.raises(GXWFormatError):
        generate_object_project(model)


def test_preview_escapes_symbols_as_xml_text():
    p, _, _ = read_project(default_baseline())
    p = replace(p, nodes=(replace(p.nodes[0], symbol='<script>alert("x")</script>'), *p.nodes[1:]))
    svg = render_structured_svg(p)
    root = ET.fromstring(svg)
    assert not root.findall('.//{http://www.w3.org/2000/svg}script')
    assert '&lt;script&gt;' in svg


def test_ladder_conversion_retains_series_parallel_and_multiple_outputs():
    ladder = {"device_comments": {}, "rungs": [{"rung_id": 1, "shared_inputs": [{"type": "NO", "address": "X0"}],
        "branches": [{"inputs": [{"type": "parallel_block", "branches": [
            [{"type": "NO", "address": "X1"}], [{"type": "NC", "address": "X2"}]]}],
            "outputs": [{"type": "COIL", "address": "Y0"}, {"type": "COIL", "address": "Y1"}]}]},
        {"rung_id": 2, "branches": [{"inputs": [{"type": "NO", "address": "X3"}],
                                     "outputs": [{"type": "COIL", "address": "Y2"}]}]}]}
    result = generate_object_project(ladder_to_object_model(ladder))
    p, _, _ = read_project(result.data)
    from src.gxw.connectivity import build_connectivity_graph
    graph = build_connectivity_graph(p)
    by_name = {n.symbol: n for n in p.nodes}
    for port in (0, 1):
        assert graph.ports_connected(by_name['X1'].offset, port, by_name['X2'].offset, port)
    assert graph.ports_connected(by_name['X0'].offset, 1, by_name['X1'].offset, 0)
    assert graph.ports_connected(by_name['X1'].offset, 1, by_name['Y0'].offset, 0)
    assert graph.ports_connected(by_name['Y0'].offset, 0, by_name['Y1'].offset, 0)
    assert not graph.ports_connected(by_name['Y0'].offset, 0, by_name['Y2'].offset, 0)
    assert by_name['X2'].kind == NodeKind.CONTACT_NC
