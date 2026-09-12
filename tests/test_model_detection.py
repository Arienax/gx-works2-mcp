from application.model_detection import inspect_openai_compatible
from model_provider import TextDelta, ToolCallEnd
from tool_messages import ToolCall


class _Provider:
    def list_models(self, *, timeout=None):
        assert timeout == 15.0
        return ("model-b", "model-a", "model-b")

    def stream(self, request):
        assert request.timeout == 15.0
        assert request.max_retries == 0
        if request.tools:
            yield ToolCallEnd(ToolCall("probe-1", "capability_probe", '{"value":"ok"}'))
        else:
            yield TextDelta('{"probe":true}')


def test_discovery_sorts_models_selects_recommended_and_probes_common_capabilities():
    result = inspect_openai_compatible(
        _Provider(),
        "__discover__",
        {"reasoning": True, "tools": False, "structured_output": False},
    )
    assert result["models"] == ["model-a", "model-b"]
    assert result["recommended_model"] == "model-a"
    assert result["selected_model_available"] is False
    assert result["capabilities"]["reasoning"] is True
    assert result["capabilities"]["tools"] is True
    assert result["capabilities"]["structured_output"] is True
    assert result["detected"] == ["structured_output", "tools"]
