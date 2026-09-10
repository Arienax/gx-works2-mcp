"""Deterministic SVG preview of the parsed native object graph."""
from html import escape

from .models import NodeKind
from .object_model import _port_names


def render_structured_svg(program):
    unit, margin = 34, 42
    right = max([1, *[n.bbox.right for n in program.nodes], *[max(w.start.x, w.end.x) for w in program.wires]])
    bottom = max([program.canvas_height, *[n.bbox.bottom for n in program.nodes]])
    width, height = right * unit + 2 * margin, bottom * unit + 2 * margin
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="Structured Ladder FBD">',
             '<style>text{font-family:Consolas,"Microsoft YaHei",sans-serif;font-size:13px;fill:#213349}'
             '.wire{stroke:#58748e;stroke-width:2;fill:none}.node{stroke:#254a6e;stroke-width:2;fill:#f4f8fc}'
             '.symbol{font-size:15px;fill:#174f7d}.port{fill:#fff;stroke:#254a6e;stroke-width:1.5}</style>',
             f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
             f'<g transform="translate({margin} {margin})">']
    for w in program.wires:
        parts.append(f'<path class="wire" d="M{w.start.x*unit},{w.start.y*unit} L{w.end.x*unit},{w.end.y*unit}"/>')
    for n in program.nodes:
        x, y = n.bbox.left*unit, n.bbox.top*unit
        width, height = (n.bbox.right-n.bbox.left)*unit, (n.bbox.bottom-n.bbox.top)*unit
        parts.append(f'<g data-node-offset="{n.offset}"><title>{escape(n.symbol)}{escape(": "+n.type_name) if n.type_name else ""}</title>')
        if n.kind in (NodeKind.CONTACT, NodeKind.CONTACT_NC, NodeKind.COIL):
            cy = n.port_point(0).y * unit
            parts.append(f'<path class="wire" d="M{x},{cy} H{x+width/3} M{x+width*2/3},{cy} H{x+width}"/>')
            if n.kind == NodeKind.COIL:
                parts.append(f'<path class="wire" d="M{x+width*.42},{cy-11} Q{x+width*.15},{cy} {x+width*.42},{cy+11} M{x+width*.58},{cy-11} Q{x+width*.85},{cy} {x+width*.58},{cy+11}"/>')
            else:
                parts.append(f'<path class="wire" d="M{x+width/3},{cy-11} V{cy+11} M{x+width*2/3},{cy-11} V{cy+11}"/>')
                if n.kind == NodeKind.CONTACT_NC:
                    parts.append(f'<path class="wire" d="M{x+width*.27},{cy+12} L{x+width*.73},{cy-12}"/>')
            parts.append(f'<text class="symbol" x="{x+width/2}" y="{cy-18}" text-anchor="middle">{escape(n.symbol)}</text>')
        elif n.kind in (NodeKind.INPUT, NodeKind.OUTPUT):
            point = n.port_point(0)
            source = n.kind == NodeKind.INPUT
            parts.append(f'<text class="symbol" x="{point.x*unit+(-6 if source else 6)}" y="{point.y*unit-6}" text-anchor="{"end" if source else "start"}">{escape(n.symbol)}</text>')
        else:
            parts.append(f'<rect class="node" x="{x}" y="{y+unit}" width="{width}" height="{max(unit,height-unit)}" rx="3"/>')
            if n.type_name:
                parts.append(f'<text class="symbol" x="{x+width/2}" y="{y+unit*.6}" text-anchor="middle">{escape(n.symbol)}</text>')
            parts.append(f'<text x="{x+width/2}" y="{y+unit*1.45}" text-anchor="middle">{escape(n.type_name or n.symbol)}</text>')
            for name, port in zip(_port_names(n), n.ports):
                px, py = n.port_point(n.ports.index(port)).x*unit, n.port_point(n.ports.index(port)).y*unit
                left = port.local_x == 0
                parts.append(f'<text x="{px+(6 if left else -6)}" y="{py-5}" text-anchor="{"start" if left else "end"}">{escape(name)}</text>')
        for i in range(len(n.ports)):
            p = n.port_point(i)
            parts.append(f'<circle class="port" cx="{p.x*unit}" cy="{p.y*unit}" r="3"/>')
        parts.append('</g>')
    parts.extend(['</g>', '</svg>'])
    return "".join(parts)
