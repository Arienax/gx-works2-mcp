"""Bounded OpenAI-compatible model discovery and capability probes.

This module is intentionally UI/application-side.  It does not change the
ModelProvider contract or PLC runtime.  Probes are best-effort and never persist
settings by themselves.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Mapping

from model_provider import (
    ModelRequest,
    SystemMessage,
    TextDelta,
    ToolCallEnd,
    UserMessage,
)


def _consume(provider, request):
    return list(provider.stream(request))


def _tool_probe(provider, model: str) -> bool:
    tool = {
        "type": "function",
        "function": {
            "name": "capability_probe",
            "description": "Return the fixed probe value.",
            "parameters": {
                "type": "object",
                "properties": {"value": {"type": "string", "enum": ["ok"]}},
                "required": ["value"],
                "additionalProperties": False,
            },
        },
    }
    request = ModelRequest(
        messages=(
            SystemMessage("This is a capability probe. Follow the user instruction exactly."),
            UserMessage("Call capability_probe exactly once with value='ok'. Do not answer with prose."),
        ),
        model=model,
        tools=(tool,),
        stream=False,
        timeout=15.0,
        max_retries=0,
        options={"response_format": None},
    )
    try:
        events = _consume(provider, request)
    except Exception:
        return False
    return any(isinstance(event, ToolCallEnd) and event.tool_call.name == "capability_probe" for event in events)


def _structured_output_probe(provider, model: str) -> bool:
    request = ModelRequest(
        messages=(
            SystemMessage("Return only valid JSON."),
            UserMessage('Return exactly one JSON object with key "probe" and value true.'),
        ),
        model=model,
        stream=False,
        timeout=15.0,
        max_retries=0,
        options={"response_format": {"type": "json_object"}},
    )
    try:
        text = "".join(
            event.text for event in _consume(provider, request) if isinstance(event, TextDelta)
        ).strip()
        payload = json.loads(text)
    except Exception:
        return False
    return isinstance(payload, Mapping) and payload.get("probe") is True


def inspect_openai_compatible(provider, model: str, configured_capabilities=None) -> Dict[str, Any]:
    """Discover model ids and probe capabilities that can be tested safely.

    Tool calling and JSON-object structured output are actively probed.  Other
    capability flags are preserved from the selected profile because reasoning,
    multimodal support and provider-specific thinking controls cannot be safely
    inferred from a generic text-only OpenAI-compatible request.
    """
    models = sorted(set(provider.list_models(timeout=15.0)))
    selected = str(model or "").strip()
    probe_model = selected if selected in models else (models[0] if models else selected)
    capabilities = dict(configured_capabilities or {})
    detected = {
        "tools": _tool_probe(provider, probe_model) if probe_model else False,
        "structured_output": _structured_output_probe(provider, probe_model) if probe_model else False,
    }
    capabilities.update(detected)
    return {
        "models": models,
        "recommended_model": probe_model or None,
        "selected_model_available": bool(selected and selected in models),
        "capabilities": capabilities,
        "detected": sorted(detected),
        "note": "已自动检测工具调用与结构化输出；推理、视觉和供应商专用参数保留现有配置，可在高级设置中手动调整。",
    }
