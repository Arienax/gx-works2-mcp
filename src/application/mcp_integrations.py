"""Operator-triggered local MCP onboarding.

This service never receives arbitrary commands from the browser.  It can bind
the current GXWorks project to the private local MCP credential, exercise the
actual product launcher, and register that fixed launcher with the local Codex
CLI.  PLC engineering operations remain in ToolRuntime.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from integrations.mcp.service_credentials import bind_project, load_service_binding
from integrations.mcp.service_client import validate_service_url


class MCPIntegrationError(RuntimeError):
    pass


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def launcher_invocation() -> list[str]:
    """Return a fixed launcher command; users never need its Python internals."""
    if getattr(sys, "frozen", False):
        companion = Path(sys.executable).resolve().with_name("gxworks-agent-mcp.exe")
        if companion.is_file():
            return [str(companion)]
        raise MCPIntegrationError("发布包缺少 gxworks-agent-mcp.exe。")
    script = _root() / "scripts" / "mcp_entry.py"
    if not script.is_file():
        raise MCPIntegrationError("源码 MCP launcher 不完整。")
    return [str(Path(sys.executable).resolve()), str(script)]


def _run(parts: list[str], *, timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    command = parts
    if os.name == "nt" and Path(parts[0]).suffix.lower() in {".cmd", ".bat"}:
        command = ["cmd.exe", "/d", "/s", "/c", subprocess.list2cmdline(parts)]
    try:
        return subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=timeout,
            creationflags=flags,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise MCPIntegrationError("本机集成命令无法启动或超时。") from error


def _codex_executable() -> str | None:
    for name in ("codex", "codex.exe", "codex.cmd"):
        value = shutil.which(name)
        if value:
            return value
    return None


def _codex_config_path() -> Path:
    home = os.environ.get("CODEX_HOME", "").strip()
    return Path(home).expanduser() / "config.toml" if home else Path.home() / ".codex" / "config.toml"


def _restore_config(path: Path, original: bytes | None) -> None:
    try:
        if original is None:
            if path.exists():
                path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(original)
    except OSError:
        pass


def status(project_id: str, service_url: str) -> dict[str, Any]:
    service_url = validate_service_url(service_url)
    binding = load_service_binding() or {}
    codex = _codex_executable()
    return {
        "service_url": service_url,
        "project_id": project_id,
        "bound_project_id": binding.get("project_id") if binding.get("service_url") == service_url else None,
        "credential_ready": bool(binding and binding.get("service_url") == service_url),
        "launcher_ready": _launcher_ready(),
        "codex_cli_available": bool(codex),
        "codex_command": Path(codex).name if codex else None,
    }


def _launcher_ready() -> bool:
    try:
        launcher_invocation()
        return True
    except MCPIntegrationError:
        return False


def test_connection(project_id: str, service_url: str) -> dict[str, Any]:
    service_url = validate_service_url(service_url)
    binding = bind_project(project_id)
    if binding["service_url"] != service_url:
        raise MCPIntegrationError("当前浏览器连接的 Web 服务与本机 MCP 凭据不一致，请重启当前 Web 工作台。")
    result = _run([*launcher_invocation(), "--check"], timeout=20.0)
    if result.returncode != 0:
        raise MCPIntegrationError("MCP launcher 无法通过当前 Web 服务认证。")
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as error:
        raise MCPIntegrationError("MCP launcher 返回了无效的连接检查结果。") from error
    if payload.get("ok") is not True or payload.get("project_id") != project_id:
        raise MCPIntegrationError("MCP launcher 未绑定到当前工程。")
    return {
        "status": "connected",
        "project_id": project_id,
        "service_url": service_url,
        "tool_count": int(payload.get("tool_count") or 0),
        "message": "MCP launcher 已通过本机凭据连接当前 Web 工程。",
    }


def connect_codex(project_id: str, service_url: str) -> dict[str, Any]:
    """Replace only the named `gxworks` Codex MCP entry after a launcher check.

    The user's Codex config bytes are restored if the CLI update fails, so an
    explicit Connect click cannot strand a previously working configuration.
    """
    check = test_connection(project_id, service_url)
    codex = _codex_executable()
    if not codex:
        return {
            **check,
            "status": "codex_unavailable",
            "codex_connected": False,
            "message": "MCP 本身连接正常，但未在 PATH 中检测到 Codex CLI。可在高级设置复制配置。",
        }

    config_path = _codex_config_path()
    try:
        original = config_path.read_bytes() if config_path.is_file() else None
    except OSError as error:
        raise MCPIntegrationError("无法读取 Codex 配置文件。") from error

    # `codex mcp add` has no safe in-place replace primitive.  The operator
    # explicitly requested replacement of our fixed gxworks entry, and the
    # complete original config is restored if either CLI operation fails.
    removed = _run([codex, "mcp", "remove", "gxworks"], timeout=15.0)
    added = _run([codex, "mcp", "add", "gxworks", "--", *launcher_invocation()], timeout=20.0)
    if added.returncode != 0:
        _restore_config(config_path, original)
        raise MCPIntegrationError("Codex MCP 配置写入失败，原配置已恢复。")

    listed = _run([codex, "mcp", "list"], timeout=15.0)
    if listed.returncode != 0 or "gxworks" not in (listed.stdout + listed.stderr).lower():
        _restore_config(config_path, original)
        raise MCPIntegrationError("Codex 未确认 gxworks MCP 注册，原配置已恢复。")

    return {
        **check,
        "status": "connected",
        "codex_connected": True,
        "replaced_existing": removed.returncode == 0,
        "message": "Codex 已连接 GXWorks Agent。以后直接描述 PLC 任务即可，无需再次粘贴 MCP 配置。",
    }
