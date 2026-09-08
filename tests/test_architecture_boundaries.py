import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"


def _imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
    return found


def _transport_field_accesses(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    fields = {"choices", "delta", "reasoning_content"}
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in fields:
            found.append((node.lineno, node.attr))
        elif isinstance(node, ast.Subscript):
            key = node.slice
            if isinstance(key, ast.Constant) and key.value in fields:
                found.append((node.lineno, key.value))
    return found


def test_plc_and_gx_core_do_not_import_model_or_vendor_clients():
    core_files = [
        SOURCE_ROOT / "plc_core.py",
        SOURCE_ROOT / "plc_generation_contract.py",
        SOURCE_ROOT / "plc_ir.py",
        SOURCE_ROOT / "plc_json_validator.py",
        SOURCE_ROOT / "plc_semantics.py",
        SOURCE_ROOT / "plc_static_analyzer.py",
        SOURCE_ROOT / "plc_timing.py",
        SOURCE_ROOT / "plc_st_renderer.py",
        SOURCE_ROOT / "draw.py",
        *sorted((SOURCE_ROOT / "gxworks2").rglob("*.py")),
        *sorted((SOURCE_ROOT / "simulator").rglob("*.py")),
    ]
    forbidden_roots = {
        "openai",
        "anthropic",
        "zhipuai",
        "model_provider",
        "plc_agent",
        "mcp",
        "mcp_types",
        "integrations",
    }

    violations = []
    for path in core_files:
        for imported in _imports(path):
            if imported.split(".", 1)[0] in forbidden_roots:
                violations.append(f"{path.relative_to(ROOT)} -> {imported}")
    assert violations == []


def test_provider_does_not_import_plc_gx_or_automation_implementation():
    forbidden_roots = {"plc_ir", "plc_core", "gxworks2", "simulator", "pywinauto", "draw"}
    violations = [
        imported
        for imported in _imports(SOURCE_ROOT / "model_provider.py")
        if imported.split(".", 1)[0] in forbidden_roots
    ]
    assert violations == []


def test_agent_depends_on_runtime_not_plc_implementation():
    imports = _imports(SOURCE_ROOT / "plc_agent.py")
    forbidden_roots = {"plc_core", "plc_ir", "plc_agent_tools", "gxworks2", "pywinauto"}
    assert [
        imported
        for imported in imports
        if imported.split(".", 1)[0] in forbidden_roots
    ] == []
    assert "tool_runtime" in imports
    assert "model_provider" in imports


def test_only_model_provider_imports_openai_sdk():
    violations = []
    for path in SOURCE_ROOT.rglob("*.py"):
        if path.name == "model_provider.py":
            continue
        if any(imported.split(".", 1)[0] == "openai" for imported in _imports(path)):
            violations.append(str(path.relative_to(ROOT)))
    assert violations == []


def test_agent_and_api_do_not_parse_vendor_response_fields():
    assert _transport_field_accesses(SOURCE_ROOT / "api.py") == []
    assert _transport_field_accesses(SOURCE_ROOT / "plc_agent.py") == []


def test_mcp_adapters_do_not_import_plc_or_desktop_implementations():
    adapter_root = SOURCE_ROOT / "integrations" / "mcp"
    forbidden = {
        "plc_core", "plc_ir", "plc_json_validator", "plc_semantics",
        "plc_static_analyzer", "plc_timing", "draw", "inspection_engine",
        "knowledge_retriever", "gxworks2", "simulator", "pywinauto",
        "qt_compat", "PyQt5", "PyQt6", "main", "plc_agent", "openai",
        "api", "model_provider", "config", "config_manager", "credential_store",
    }
    violations = [
        f"{path.relative_to(ROOT)} -> {imported}"
        for path in adapter_root.rglob("*.py")
        for imported in _imports(path)
        if imported.split(".", 1)[0] in forbidden
    ]
    assert violations == []
    assert "tool_runtime" in _imports(adapter_root / "tool_adapter.py")
    assert "tool_runtime" in _imports(adapter_root / "server.py")
    assert "session_store" in _imports(adapter_root / "context_provider.py")


def test_runtime_and_builtin_agent_do_not_depend_on_optional_mcp_sdk():
    for name in ("tool_runtime.py", "tool_messages.py", "plc_generation_contract.py", "plc_agent.py", "plc_agent_tools.py", "model_provider.py", "session_store.py"):
        assert not {"mcp", "mcp_types", "integrations"}.intersection(
            imported.split(".", 1)[0] for imported in _imports(SOURCE_ROOT / name)
        )


def test_generation_contract_and_tool_messages_depend_only_on_standard_library():
    allowed = {"__future__", "copy", "re", "typing", "dataclasses"}
    for name in ("plc_generation_contract.py", "tool_messages.py"):
        assert {item.split(".", 1)[0] for item in _imports(SOURCE_ROOT / name)} <= allowed


def test_external_tool_runtime_has_no_model_or_credential_dependency():
    forbidden = {"api", "model_provider", "config", "config_manager", "credential_store", "openai", "qt_compat", "PyQt5", "PyQt6"}
    for name in ("tool_runtime.py", "tool_messages.py", "plc_agent_tools.py", "plc_generation_contract.py"):
        assert not forbidden.intersection(item.split(".", 1)[0] for item in _imports(SOURCE_ROOT / name))


def test_model_provider_reexports_the_same_neutral_tool_types():
    import model_provider
    import tool_messages

    assert model_provider.ToolCall is tool_messages.ToolCall
    assert model_provider.ToolResult is tool_messages.ToolResult
