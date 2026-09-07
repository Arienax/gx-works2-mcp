# GXWorks Agent

[English](README.md)

面向三菱 FX 系列 PLC 的 AI 辅助工程工作台。内置 Agent 可以根据自然语言需求生成梯形图或 ST 程序，并通过本地确定性规则完成指令、软元件、I/O、时序和程序结构校验。外部 MCP 客户端通过同一个 ToolRuntime 使用现有工程工具。

## 主要功能

- PLC 程序生成、版本管理、差异预览、评审与故障调试
- GX Works2 CSV 与软元件注释导入导出、双向同步
- GX Simulator2 自动化回归测试与可读测试报告
- FX3U 手册 RAG 检索、模型工具调用和图片需求输入
- DeepSeek、智谱及自定义 OpenAI-compatible 模型配置

| 集成 | 状态 | 已有范围 |
| --- | --- | --- |
| 内置 Agent | 可用 | ModelProvider 与共享 ToolRuntime |
| 独立 MCP 服务 | **可用（Working）** | stdio 工具发现与调用、已保存项目快照；单元测试和真实进程烟测通过 |
| Codex 作为 MCP 客户端 | 已提供配置示例 | 使用相同服务和工具，不另建 Codex 专用 PLC 逻辑 |
| Streamable HTTP / 桌面上下文桥接 | 计划中 | 当前 CLI 未提供 |
| Codex Harness / App Server | **计划中（Planned）** | 尚未实现 |

候选补丁和 GX 导入工具保持 `confirmation_required`。独立服务尚无批准执行接口，也不会把请求送入桌面确认界面。不暴露任意桌面控制、无限制 PLC 写入或强制软元件操作。

## 启动 MCP 服务

使用独立的 Python 3.10+ 环境，在仓库根目录的 PowerShell 中执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-mcp.txt
$env:PYTHONPATH = (Resolve-Path .\src).Path
.\.venv\Scripts\python.exe -m integrations.mcp --stdio --workspace '<已有工作区路径>' --project '<项目ID>'
```

路径须指向现有 SessionStore 工作区。项目 ID、版本选择、确认语义和验证方式见 [MCP 接入文档](docs/integrations/mcp.md)；Codex 配置和未来 Harness 边界见 [Codex 接入文档](docs/integrations/codex.md)。

MCP 依赖单独放在 `requirements-mcp.txt`，不改变桌面版的 `requirements.txt` 或 Windows 7 的 `requirements-win7.txt`。实际 GX/仿真集成仍需对应 Windows 软件；MCP 单元测试和烟测不需要这些软件或真实 PLC。

```text
python -m pytest -q
python scripts/mcp_smoke.py
```

请在装有对应依赖的环境中运行。未安装可选 MCP SDK 时，MCP 测试模块会跳过；烟测需要该 SDK，不能以跳过代替验证通过。

## 技术栈

- Python、PyQt、PyInstaller
- 统一 ModelProvider、共享 ToolRuntime 与官方 Python MCP SDK
- PLC IR、静态校验器及 SVG/CSV/ST 确定性渲染
- SQLite FTS5、BM25、Dense Vector 与混合重排
- pywinauto、MX Component 与本地 C# 仿真网关

桌面 API Key 仅保存在当前 Windows 用户的凭据管理器中，不写入源码仓库。独立 MCP 服务不需要模型 API Key。
