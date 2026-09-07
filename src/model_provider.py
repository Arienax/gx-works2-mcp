"""Vendor-neutral model messages and the OpenAI-compatible transport."""

from __future__ import annotations

import copy
import base64
import json
import threading
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, Iterable, Iterator, Mapping, Optional, Protocol, Sequence, Tuple, Union

from i18n import get_language, response_language_instruction


@dataclass(frozen=True)
class SystemMessage:
    content: Any


@dataclass(frozen=True)
class ImageAttachment:
    """Vendor-neutral inline image carried only by a user message."""

    filename: str
    media_type: str
    data: bytes

    def __post_init__(self):
        media_type = str(self.media_type or "").strip().lower()
        if media_type not in {
            "image/jpeg",
            "image/png",
            "image/gif",
            "image/webp",
        }:
            raise ValueError(f"不支持的图片格式：{media_type or '未知格式'}")
        if not isinstance(self.data, bytes) or not self.data:
            raise ValueError("图片附件内容为空。")
        if len(self.data) > 32 * 1024 * 1024:
            raise ValueError("单张图片不能超过 32 MiB。")
        object.__setattr__(self, "filename", str(self.filename or "图片"))
        object.__setattr__(self, "media_type", media_type)


@dataclass(frozen=True)
class UserMessage:
    content: Any
    images: Tuple[ImageAttachment, ...] = ()


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: Any = field(default_factory=dict)


@dataclass(frozen=True)
class AssistantMessage:
    content: str = ""
    tool_calls: Tuple[ToolCall, ...] = ()
    reasoning: str = ""


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    name: str
    content: str
    data: Mapping[str, Any] = field(default_factory=dict)
    is_error: bool = False


ModelMessage = Union[SystemMessage, UserMessage, AssistantMessage, ToolResult]


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ReasoningDelta:
    text: str


@dataclass(frozen=True)
class ToolCallStart:
    call_id: str
    name: str


@dataclass(frozen=True)
class ToolCallEnd:
    tool_call: ToolCall


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


ModelEvent = Union[TextDelta, ReasoningDelta, ToolCallStart, ToolCallEnd, Usage]


@dataclass(frozen=True)
class ModelRequest:
    messages: Tuple[ModelMessage, ...]
    model: Optional[str] = None
    tools: Tuple[Mapping[str, Any], ...] = ()
    options: Mapping[str, Any] = field(default_factory=dict)
    stream: bool = True
    timeout: Optional[float] = None
    max_retries: Optional[int] = None
    response_language: str = field(default_factory=lambda: get_language())

    @classmethod
    def from_messages(
        cls,
        messages: Sequence[Union[ModelMessage, Mapping[str, Any]]],
        **kwargs: Any,
    ) -> "ModelRequest":
        return cls(tuple(coerce_message(item) for item in messages), **kwargs)


@dataclass(frozen=True)
class CollectedResponse:
    message: AssistantMessage
    usage: Optional[Usage] = None


def with_response_language(request: ModelRequest) -> ModelRequest:
    """Apply the application preference to every model path without mutating history."""
    instruction = response_language_instruction(request.response_language)
    messages = list(request.messages)
    for index, message in enumerate(messages):
        if isinstance(message, SystemMessage):
            content = str(message.content or "")
            if instruction not in content:
                messages[index] = replace(message, content=content + "\n\n" + instruction)
            break
    else:
        messages.insert(0, SystemMessage(instruction))
    return replace(request, messages=tuple(messages))


class ModelProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "provider_error",
        retryable: bool = False,
        status_code: Optional[int] = None,
    ):
        super().__init__(message)
        self.code = code
        self.retryable = bool(retryable)
        self.status_code = status_code


class ModelProvider(Protocol):
    def stream(self, request: ModelRequest) -> Iterator[ModelEvent]: ...


def _value(owner: Any, name: str, default: Any = None) -> Any:
    if isinstance(owner, Mapping):
        return owner.get(name, default)
    return getattr(owner, name, default)


def _tool_call_from_value(value: Any) -> ToolCall:
    function = _value(value, "function", {})
    arguments = _value(function, "arguments", "{}")
    return ToolCall(
        id=str(_value(value, "id", "") or ""),
        name=str(_value(function, "name", "") or ""),
        arguments=arguments,
    )


def coerce_message(value: Union[ModelMessage, Mapping[str, Any]]) -> ModelMessage:
    if isinstance(value, (SystemMessage, UserMessage, AssistantMessage, ToolResult)):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("model message must be a canonical message or mapping")
    role = str(value.get("role") or "").strip().lower()
    if role == "system":
        return SystemMessage(value.get("content", ""))
    if role == "user":
        images = []
        for item in value.get("images", ()) or ():
            if isinstance(item, ImageAttachment):
                images.append(item)
                continue
            if not isinstance(item, Mapping):
                raise TypeError("user message image must be an ImageAttachment or mapping")
            raw_data = item.get("data", b"")
            if isinstance(raw_data, str):
                raw_data = base64.b64decode(raw_data, validate=True)
            images.append(
                ImageAttachment(
                    str(item.get("filename") or "图片"),
                    str(item.get("media_type") or ""),
                    raw_data,
                )
            )
        return UserMessage(value.get("content", ""), tuple(images))
    if role == "assistant":
        return AssistantMessage(
            content=str(value.get("content") or ""),
            reasoning=str(
                value.get("reasoning") or value.get("reasoning_content") or ""
            ),
            tool_calls=tuple(
                _tool_call_from_value(item)
                for item in (value.get("tool_calls") or [])
            ),
        )
    if role == "tool":
        return ToolResult(
            call_id=str(value.get("tool_call_id") or value.get("call_id") or ""),
            name=str(value.get("name") or ""),
            content=str(value.get("content") or ""),
            is_error=bool(value.get("is_error", False)),
        )
    raise ValueError(f"unsupported model message role: {role!r}")


def strip_legacy_provider_fields(value: Mapping[str, Any]) -> Dict[str, Any]:
    """Remove transport-only fields from legacy domain snapshots."""

    return {
        key: copy.deepcopy(item)
        for key, item in value.items()
        if key not in {"reasoning_content", "raw_response"}
    }


def _deep_merge(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> Dict[str, Any]:
    result = copy.deepcopy(dict(base))
    for key, value in overlay.items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _wire_arguments(arguments: Any) -> str:
    if isinstance(arguments, str):
        return arguments
    return json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))


def _wire_message(message: ModelMessage) -> Dict[str, Any]:
    if isinstance(message, SystemMessage):
        return {"role": "system", "content": message.content}
    if isinstance(message, UserMessage):
        if not message.images:
            return {"role": "user", "content": message.content}
        content = []
        if message.content not in (None, ""):
            content.append({"type": "text", "text": str(message.content)})
        for attachment in message.images:
            encoded = base64.b64encode(attachment.data).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{attachment.media_type};base64,{encoded}"
                    },
                }
            )
        return {"role": "user", "content": content}
    if isinstance(message, ToolResult):
        return {
            "role": "tool",
            "tool_call_id": message.call_id,
            "content": message.content,
        }
    payload: Dict[str, Any] = {
        "role": "assistant",
        "content": message.content or None,
    }
    if message.reasoning:
        # Both supported OpenAI-compatible providers require this replay during
        # an interleaved thinking/tool turn.  It never leaves this adapter.
        payload["reasoning_content"] = message.reasoning
    if message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": item.id,
                "type": "function",
                "function": {
                    "name": item.name,
                    "arguments": _wire_arguments(item.arguments),
                },
            }
            for item in message.tool_calls
        ]
    return payload


def _normalize_error(error: Exception) -> ModelProviderError:
    if isinstance(error, ModelProviderError):
        return error
    status = getattr(error, "status_code", None)
    name = type(error).__name__.lower()
    if status in {401, 403} or "authentication" in name or "permission" in name:
        code, retryable = "authentication", False
    elif status == 429 or "ratelimit" in name or "rate_limit" in name:
        code, retryable = "rate_limit", True
    elif "timeout" in name:
        code, retryable = "timeout", True
    elif status == 400 or "badrequest" in name:
        code, retryable = "invalid_request", False
    elif status is not None and int(status) >= 500:
        code, retryable = "unavailable", True
    elif "connection" in name:
        code, retryable = "unavailable", True
    else:
        code, retryable = "provider_error", False
    return ModelProviderError(
        str(error), code=code, retryable=retryable, status_code=status
    )


def _usage_event(value: Any) -> Optional[Usage]:
    if value is None:
        return None
    input_tokens = int(
        _value(value, "input_tokens", _value(value, "prompt_tokens", 0)) or 0
    )
    output_tokens = int(
        _value(value, "output_tokens", _value(value, "completion_tokens", 0)) or 0
    )
    total_tokens = int(_value(value, "total_tokens", 0) or 0)
    if not total_tokens:
        total_tokens = input_tokens + output_tokens
    if not any((input_tokens, output_tokens, total_tokens)):
        return None
    return Usage(input_tokens, output_tokens, total_tokens)


class OpenAICompatibleProvider:
    """The only module that knows OpenAI SDK response and request shapes."""

    def __init__(self, profile: Mapping[str, Any], api_key: str, *, client: Any = None):
        self.profile = copy.deepcopy(dict(profile))
        self.api_key = str(api_key or "").strip()
        if str(self.profile.get("adapter") or "") != "openai_compatible":
            raise ValueError("当前版本只支持 openai_compatible adapter。")
        if not self.api_key:
            raise ValueError("未配置当前模型 Profile 的 API Key。")
        self._client = client or self._create_client()

    def _create_client(self):
        from openai import OpenAI

        return OpenAI(
            api_key=self.api_key,
            base_url=str(self.profile.get("baseUrl") or "").strip(),
        )

    def _request_params(self, request: ModelRequest) -> Dict[str, Any]:
        request = with_response_language(request)
        params = _deep_merge(
            self.profile.get("generationDefaults") or {},
            request.options or {},
        )
        capabilities = self.profile.get("capabilities") or {}
        image_attachments = [
            image
            for message in request.messages
            if isinstance(message, UserMessage)
            for image in message.images
        ]
        if image_attachments and not capabilities.get("multimodal"):
            model = str(request.model or self.profile.get("model") or "当前模型")
            raise ModelProviderError(
                f"模型 {model} 不支持图片输入，请切换到带视觉能力的模型。",
                code="image_not_supported",
            )
        encoded_bytes = sum(
            4 * ((len(image.data) + 2) // 3) for image in image_attachments
        )
        if encoded_bytes > 45 * 1024 * 1024:
            raise ModelProviderError(
                "图片编码后的请求体过大，请减少图片数量或压缩图片。",
                code="image_payload_too_large",
            )
        extra_body = copy.deepcopy(params.get("extra_body") or {})
        if capabilities.get("thinking_required"):
            thinking = copy.deepcopy(extra_body.get("thinking") or {})
            thinking["type"] = "enabled"
            extra_body["thinking"] = thinking
        if capabilities.get("tool_stream") and request.stream and request.tools:
            extra_body["tool_stream"] = True
        if extra_body:
            params["extra_body"] = extra_body
        params = _deep_merge(params, self.profile.get("requestOverrides") or {})

        params["model"] = request.model or str(self.profile.get("model") or "")
        params["messages"] = [_wire_message(item) for item in request.messages]
        params["stream"] = bool(request.stream)
        if request.tools:
            params["tools"] = copy.deepcopy(list(request.tools))
            params.setdefault("tool_choice", "auto")
        else:
            params.pop("tools", None)
            params.pop("tool_choice", None)
        thinking = (params.get("extra_body") or {}).get("thinking") or {}
        if (
            request.tools
            and capabilities.get("disable_tool_choice_with_thinking")
            and str(thinking.get("type") or "").lower() == "enabled"
        ):
            params.pop("tool_choice", None)
        return params

    def stream(self, request: ModelRequest) -> Iterator[ModelEvent]:
        client = self._client
        options = {}
        if request.timeout is not None:
            options["timeout"] = request.timeout
        if request.max_retries is not None:
            options["max_retries"] = request.max_retries
        if options:
            client = client.with_options(**options)
        try:
            response = client.chat.completions.create(**self._request_params(request))
            if request.stream:
                yield from self._streaming_events(response)
            else:
                yield from self._complete_events(response)
        except Exception as error:
            raise _normalize_error(error) from error

    def _complete_events(self, response: Any) -> Iterator[ModelEvent]:
        choices = list(_value(response, "choices", []) or [])
        if not choices:
            raise ModelProviderError("AI 未返回任何候选结果。", code="protocol")
        message = _value(choices[0], "message")
        if message is None:
            raise ModelProviderError("AI 返回结果缺少 message。", code="protocol")
        reasoning = str(_value(message, "reasoning_content", "") or "")
        content = str(_value(message, "content", "") or "")
        if reasoning:
            yield ReasoningDelta(reasoning)
        if content:
            yield TextDelta(content)
        for index, raw_call in enumerate(_value(message, "tool_calls", []) or []):
            call = _tool_call_from_value(raw_call)
            if not call.id:
                call = replace(call, id=f"tool_call_{index}")
            yield ToolCallStart(call.id, call.name)
            yield ToolCallEnd(call)
        usage = _usage_event(_value(response, "usage", None))
        if usage is not None:
            yield usage

    def _streaming_events(self, response: Iterable[Any]) -> Iterator[ModelEvent]:
        fragments: Dict[int, Dict[str, Any]] = {}
        latest_usage = None
        for chunk in response:
            usage = _usage_event(_value(chunk, "usage", None))
            if usage is not None:
                latest_usage = usage
            choices = list(_value(chunk, "choices", []) or [])
            if not choices:
                continue
            delta = _value(choices[0], "delta")
            if delta is None:
                continue
            reasoning = str(_value(delta, "reasoning_content", "") or "")
            content = str(_value(delta, "content", "") or "")
            if reasoning:
                yield ReasoningDelta(reasoning)
            if content:
                yield TextDelta(content)
            for fallback_index, raw_call in enumerate(
                _value(delta, "tool_calls", []) or []
            ):
                raw_index = _value(raw_call, "index", fallback_index)
                try:
                    index = int(raw_index)
                except (TypeError, ValueError):
                    index = fallback_index
                fragment = fragments.setdefault(
                    index,
                    {"id": "", "name": "", "arguments": ""},
                )
                fragment["id"] += str(_value(raw_call, "id", "") or "")
                function = _value(raw_call, "function", {})
                fragment["name"] += str(_value(function, "name", "") or "")
                arguments = _value(function, "arguments", "")
                if arguments not in (None, ""):
                    fragment["arguments"] += _wire_arguments(arguments)
        for index in sorted(fragments):
            fragment = fragments[index]
            call = ToolCall(
                fragment["id"] or f"tool_call_{index}",
                fragment["name"],
                fragment["arguments"] or "{}",
            )
            yield ToolCallStart(call.id, call.name)
            yield ToolCallEnd(call)
        if latest_usage is not None:
            yield latest_usage

    def list_models(self, *, timeout: Optional[float] = None) -> Sequence[str]:
        try:
            client = self._client
            if timeout is not None:
                client = client.with_options(timeout=timeout, max_retries=0)
            response = client.models.list()
            return tuple(
                str(_value(item, "id", ""))
                for item in (_value(response, "data", []) or [])
                if _value(item, "id", None)
            )
        except Exception as error:
            raise _normalize_error(error) from error


def collect_response(
    provider: ModelProvider,
    request: ModelRequest,
    *,
    on_reasoning_chunk: Optional[Callable[[str], None]] = None,
    on_content_chunk: Optional[Callable[[str], None]] = None,
    on_event: Optional[Callable[[ModelEvent], None]] = None,
    fallback_to_non_stream: bool = False,
    on_fallback: Optional[Callable[[ModelProviderError], None]] = None,
) -> CollectedResponse:
    request = with_response_language(request)
    def consume(current: ModelRequest) -> CollectedResponse:
        reasoning = []
        content = []
        calls = []
        usage = None
        for event in provider.stream(current):
            if on_event is not None:
                on_event(event)
            if isinstance(event, ReasoningDelta):
                reasoning.append(event.text)
                if on_reasoning_chunk is not None:
                    on_reasoning_chunk(event.text)
            elif isinstance(event, TextDelta):
                content.append(event.text)
                if on_content_chunk is not None:
                    on_content_chunk(event.text)
            elif isinstance(event, ToolCallEnd):
                calls.append(event.tool_call)
            elif isinstance(event, Usage):
                usage = event
        return CollectedResponse(
            AssistantMessage("".join(content), tuple(calls), "".join(reasoning)),
            usage,
        )

    try:
        return consume(request)
    except ModelProviderError as error:
        if not (fallback_to_non_stream and request.stream):
            raise
        if on_fallback is not None:
            on_fallback(error)
        return consume(replace(request, stream=False))


_provider_lock = threading.Lock()
_provider_cache_key = None
_provider_cache: Optional[ModelProvider] = None


def create_provider(
    profile: Mapping[str, Any], api_key: str, *, client: Any = None
) -> ModelProvider:
    adapter = str(profile.get("adapter") or "")
    if adapter != "openai_compatible":
        raise ValueError(f"不支持的模型 adapter：{adapter}")
    return OpenAICompatibleProvider(profile, api_key, client=client)


def get_active_provider(config: Optional[Mapping[str, Any]] = None) -> ModelProvider:
    # Canonical ToolCall/ToolResult imports must not initialize Windows
    # credentials or desktop model settings in an external tool server.
    from config_manager import get_api_key, get_model_profile, load_full_config

    global _provider_cache_key, _provider_cache
    config = dict(config) if config is not None else load_full_config()
    profile = get_model_profile(config)
    api_key = get_api_key(config, profile["id"])
    cache_key = (
        json.dumps(profile, ensure_ascii=False, sort_keys=True),
        api_key,
    )
    with _provider_lock:
        if _provider_cache is None or _provider_cache_key != cache_key:
            _provider_cache = create_provider(profile, api_key)
            _provider_cache_key = cache_key
        return _provider_cache


def reset_model_provider() -> None:
    global _provider_cache_key, _provider_cache
    with _provider_lock:
        _provider_cache_key = None
        _provider_cache = None


def reload_model_provider() -> ModelProvider:
    reset_model_provider()
    return get_active_provider()


def test_model_profile(profile: Mapping[str, Any], api_key: str) -> str:
    provider = create_provider(profile, api_key)
    model_ids = set(provider.list_models(timeout=15.0))
    selected = str(profile.get("model") or "")
    if model_ids and selected not in model_ids:
        return "连接成功；模型列表中未找到当前模型，请确认模型名称。"
    return "连接成功，API Key 和服务地址有效。"


def sdk_runtime_self_test() -> bool:
    """Verify packaged adapter dependencies without issuing a network request."""

    try:
        import jiter
        import pydantic
        import pydantic_core

        provider = OpenAICompatibleProvider(
            {
                "adapter": "openai_compatible",
                "baseUrl": "https://api.deepseek.com",
                "model": "offline-package-self-test",
            },
            "sk-offline-package-self-test",
        )
        return bool(provider and jiter and pydantic and pydantic_core)
    except Exception:
        return False


__all__ = [
    "AssistantMessage",
    "CollectedResponse",
    "ImageAttachment",
    "ModelEvent",
    "ModelProvider",
    "ModelProviderError",
    "ModelRequest",
    "OpenAICompatibleProvider",
    "ReasoningDelta",
    "SystemMessage",
    "TextDelta",
    "ToolCall",
    "ToolCallEnd",
    "ToolCallStart",
    "ToolResult",
    "Usage",
    "UserMessage",
    "coerce_message",
    "collect_response",
    "create_provider",
    "get_active_provider",
    "reload_model_provider",
    "reset_model_provider",
    "sdk_runtime_self_test",
    "strip_legacy_provider_fields",
    "test_model_profile",
]
