# GXWorks Agent

[English](README.md) | 简体中文

> **面向 Mitsubishi MELSEC PLC 编程、校验、工程编辑、仿真、诊断与 GX Works2 集成的 AI 工程 Agent。**  
> 自然语言 → 已确认控制规格 → PLC IR → 确定性校验 → GX Works2 / GXW → 仿真证据。

![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)
![Platform](https://img.shields.io/badge/platform-Windows-0078D6.svg)
![PLC](https://img.shields.io/badge/demo-FX3U-orange.svg)
![Status](https://img.shields.io/badge/status-active%20development-yellow.svg)

<p align="center">
  <img src="resources/assets/demo.gif" alt="GXWorks Agent 演示" width="1200">
</p>

**GXWorks Agent** 是一个面向 Mitsubishi MELSEC PLC 开发的实验性 AI 工程工作台。

项目遵循一个基本原则：**LLM 输出本身不等于工程结果。** 自然语言需求先转换为结构化控制规格和 PLC 程序表示，经过确定性校验，形成可审查的版本化候选，之后才允许通过受控操作进入 GX Works2 或 GX Simulator2。

当前实现主要聚焦于 **FX3U + GX Works2**，同时支持较成熟的 Ladder CSV 工作流，以及持续开发中的原生 **GXW / 结构化梯形图 / FBD** 工作流。

---

## 快速开始

### Windows Web 工作台

使用 Windows 发布包时，解压完整的 `GXWorks-Agent-Web` 目录，然后双击：

```text
start-web.cmd
```

选择工作区文件夹即可打开，不再选择只读／操作员角色。直接生成或编辑的程序通过校验后自动保存，历史版本保留。在 **设置 → 常规 → 操作审批** 中选择 **逐项审批**（默认）、**替我审批** 或 **完全访问**；该模式控制已支持的 GX／仿真／调试执行，不改变 PLC 校验。切换完全访问需要明确确认。仍保留显式 `-ReadOnly` 恢复参数。

顶部统一提供 **导出文件、从 GX 读取、发送到 GX** 和一个刷新／重绘按钮；导入、转换和同步检查归入 **更多**。下载文件不需要连接 GX。

后端准备就绪后，启动器会打开本机浏览器会话。使用期间保留服务窗口，结束后在该窗口按 `Ctrl+C` 停止服务。

Web 发布包无需另行安装 Python、Node.js 或 Qt。

启动工作台**不会**自动启动 GX Works2、GX Simulator2、仿真网关，也不会连接真实 PLC。

源码安装、审批边界、工作区锁、MCP 服务模式及 Windows 集成细节见 [Web 工作台使用指南](docs/integrations/web.md)。

### 源码安装

Web 源码版本先安装后端运行依赖，再使用根目录的一键前端构建脚本：

```powershell
git clone https://github.com/Arienax/gxworks-agent.git
cd gxworks-agent

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements/web.txt

.\build-web.bat --no-pause

$env:PYTHONPATH = (Resolve-Path .\src).Path
python -m integrations.web --workspace "D:\PLCWorkspaces\my-workspace" --port 8765 --open-browser
```

`build-web.bat` 固定执行 `npm ci → npm run types → npm run build`，构建结果写入 `web/dist`。

保留的 Qt 桌面开发入口仍可单独使用：

```powershell
python -m pip install -r requirements.txt
python src\main.py
```

运行测试：

```powershell
pytest -q
```

仓库还保留 Windows 7 兼容依赖：

```powershell
pip install -r requirements/win7.txt
```

API Key 保存在 Windows Credential Manager 中，不提交到仓库配置文件。

GX Works2 集成需要安装相应 Mitsubishi 软件；自动化仿真还需要 GX Simulator2 和 MX Component。仓库不包含这些商业软件。

---

## 当前功能状态

| 能力 | 状态 |
| --- | --- |
| 自然语言需求分析 | ✅ 可用 |
| 已确认控制规格工作流 | ✅ 可用 |
| PLC 中间表示（PLC IR） | ✅ 可用 |
| 确定性 PLC 校验 | ✅ 可用 |
| 梯形图 SVG 预览 | ✅ 可用 |
| Ladder CSV 生成 | ✅ 可用 |
| GX Works2 CSV 导入 / 导出 | ✅ 可用 |
| 程序与软元件注释同步 | ✅ 可用 |
| Network 级 Patch / Diff / 版本管理 | ✅ 可用 |
| 外部修改检测与冲突保护 | ✅ 可用 |
| FX3U 手册与工程知识检索 | ✅ 可用 |
| 结构化工程 Tool Runtime | ✅ 可用 |
| 本地 Web 工程工作台 | ✅ 可用 |
| 持久化任务、提案、审批与恢复 | ✅ 可用 |
| GXW 工程检查与往返写入 | 🧪 实验性 |
| 结构化梯形图 / FBD 生成 | 🧪 实验性 |
| 结构化梯形图 / FBD 对象、连线与声明编辑 | 🧪 实验性 |
| GXW 导入、预览、版本接受与下载 | 🧪 实验性 |
| 在 GX Works2 中打开已批准的 GXW 副本 | 🧪 实验性 |
| Structured Text 生成 | 🧪 实验性 |
| GX Simulator2 自动化测试规划 / 执行 | 🧪 实验性 |
| 绑定证据的调试规划与局部补丁生成 | 🧪 实验性 |
| 独立 MCP Server（stdio） | ✅ 可用 |
| 连接运行中 Web 工作台的 MCP 服务桥接 | ✅ 可用 |
| 原生 GXW 自动编译命令 | 🚧 尚未完成 |
| FBD 仿真 / 诊断 | 🚧 尚未完成 |
| 完整的任意 GXW / IEC FBD 支持 | 🚧 尚未完成 |
| GX Works3 适配器 | 📋 计划中 |
| 真实 PLC 写入路径 | 📋 当前 Web 工作流不开放 |

> 状态标记保持保守。“实验性”表示已有受控实现与测试证据，不代表它已经成为适用于任意 PLC 程序、GX 版本或 CPU 型号的通用生产级后端。

---

## 为什么需要 GXWorks Agent

传统的 LLM 工作流往往停留在：

```text
Prompt
  ↓
LLM
  ↓
PLC 代码
```

GXWorks Agent 则维护明确的工程状态：

```text
自然语言需求
      ↓
需求分析
      ↓
已确认控制规格
      ↓
PLC IR / 结构化程序模型
      ↓
确定性校验
      ↓
版本化候选 + Diff
      ↓
操作员审批
      ↓
GX Works2 / GXW
      ↓
仿真 / 证据 / 诊断
```

这种分离使系统能够利用 LLM 推理，同时由确定性的应用逻辑管理程序状态、校验、版本、审批和外部副作用。

---

## 示例

直接描述所需的设备控制行为：

```text
X0 启动电机。
X1 停止电机。
Y0 驱动电机接触器。

松开启动按钮后，电机需要保持运行。
停止必须优先于启动。

X2 检测到工件后，
延时 3 秒停止电机。

掉电恢复后电机不能自动重新启动。
```

分析阶段可以将这段需求转换为**可审查的控制规格**，包含选定的编程方案、待确认问题、参数和 I/O 分配。

只有明确确认规格后，才进入程序生成流程。

---

# Web 工程工作台

当前 Web 前端采用 React/Vite，后端由 FastAPI 提供服务。PLC 语义仍由现有 Python 工程核心负责；浏览器是操作员界面，不重复实现 PLC 逻辑。

工作台目前提供：

- 项目与版本导航
- 梯形图、FBD、ST、诊断、评审报告和仿真视图
- 自然语言分析 / 生成 / Agent 任务
- 可编辑的控制规格与确认流程
- 持久化任务进度及支持断线续读的事件历史
- 候选提案审查与 Diff 查看
- 校验通过后自动保存本地版本；GX 导入、仿真和调试按工作区审批模式执行
- 模型配置与连接测试
- GX 环境状态查看
- GXW 导入与 FBD 编辑
- 面向已有工作区的本地只读模式

浏览器刷新或关闭后，任务仍可由正在运行的后端继续处理。任务提交时会冻结项目、基础版本、已确认规格、模型设置和响应语言策略。

提案审批与版本、哈希绑定。旧浏览器标签页不能静默地将基于旧状态的候选应用到较新的活动版本。

---

# 已确认控制规格

GXWorks Agent 不假定第一段自然语言输入就是完整的 PLC 控制需求。

分析工作流可以生成包含以下内容的规格草稿：

- 需求摘要
- 候选编程方案
- 待确认问题与可选答案
- 参数与建议默认值
- I/O 分配
- 用户备注

用户在生成前确认规格。之后生成的候选与已确认规格的哈希及基础版本绑定。

这用于减少 AI 生成 PLC 程序时的一类常见问题：面对不完整的控制要求，生成语法看似合理、实际行为却不符合预期的逻辑。

---

# PLC 中间表示

内部 **PLC IR（PLC Intermediate Representation）** 是模型输出与工程操作之间的语义层。

```text
                    ┌─ Ladder CSV
                    ├─ Structured Text
AI → PLC IR ────────┼─ SVG 预览
                    ├─ 校验
                    ├─ 静态分析
                    ├─ Diff / Patch
                    ├─ 测试规划
                    └─ GX Works2 适配器
```

PLC IR 表示的工程信息包括：

- 网络（Network）
- PLC 指令
- 软元件
- 定时器与计数器
- 读写关系
- 执行触发条件
- 修订版本
- 静态分析发现
- I/O 映射
- 语义需求
- 确定性渲染
- Diff 与增量 Patch 操作

因此，每次修改都不需要让模型重新生成整份自由文本程序。

---

# 确定性校验与评审

系统不依赖模型自行宣称它生成的 PLC 程序正确。

候选可以由本地确定性代码检查，包括：

- 结构有效性
- 软元件与地址合法性
- PLC 特定的指令约束
- 定时器 / 计数器结构
- Network 结构
- I/O 引用
- 读写依赖
- 已确认规格一致性
- 多处写入同一软元件
- 自锁 / 复位归属
- 不可达状态或无法退出的状态
- 定时器完成路径
- 常见梯形图逻辑风险

评审流程首先运行本地确定性检查，再按需加入 AI 专项深度分析。即使模型不可用或调用失败，本地检查结果仍会保留。

```text
候选程序
   ↓
本地确定性检查
   ↓
可选的 AI 专项评审
   ↓
合并包含证据的报告
```

评审结果与版本绑定，可以包含严重程度、证据、受影响地址、梯级 / 网络位置以及建议的后续操作。

---

# 增量修改与版本管理

已有程序不必每次从头重新生成。

```text
当前 PLC IR
      ↓
修改要求
      ↓
Network Patch
      ↓
候选修订版本
      ↓
校验
      ↓
Diff
      ↓
自动保存本地版本
      ↓
历史版本可回退
```

例如：

```text
把停止逻辑改成停止优先。
不要修改其他 Network。
```

当前 Web 工作台在程序通过校验后自动创建并显示新的本地版本，不再要求二次接受；**不代表**程序已经导入 GX Works2、通过原生编译或完成仿真。

---

# GX Works2 梯形图集成

目前最成熟的 GX Works2 后端仍是 **Ladder CSV 导入 / 导出工作流**。

当前能力包括：

- Ladder CSV 生成
- 软元件注释 CSV 生成
- GX Works2 导入 / 导出
- 程序同步
- 注释同步
- 覆盖前自动备份
- 同步基线
- 外部人工修改检测
- 冲突保护
- 可选的往返验证

如果 GXWorks Agent 检测到 GX Works2 中的程序在上一次同步基线之后被人工修改，会停止操作，而不是静默覆盖工程人员的改动。

部分 GX Works2 操作仍依赖 GUI 自动化，因此会受到 GX 版本、界面语言、桌面状态和 Windows 会话条件的影响。

---

# 原生 GXW / 结构化梯形图 / FBD 工作流

GXWorks Agent 现已包含面向 GX Works2 结构化梯形图 / FBD 的实验性**原生 GXW 工程处理流程**。

该能力建立在逆向研究和受控的 GX Works2 编译 / 保存 / 重开实验之上。实现范围限定于已有证据支持的结构，不假定已经理解未公开字段。

当前流程可以：

- 检查 GXW 工程中选定的 `Program.pou` 记录
- 保留其他 POU 数据、元数据及未知记录
- 根据支持的结构化梯形图 / FBD 对象生成 FX3U GXW 工程
- 编辑支持的对象与正交连线
- 编辑已知的局部与全局声明
- 为支持的 FB 调用同步实例声明
- 保留导入工程中尚不支持的记录，而不是盲目重写
- 在修改后的数据流增大时扩容 CFB MiniFAT / FAT / DIFAT 分配表
- 更新必要的 GXW history 大小与 MD5 元数据
- 生成 `fbd.json`、`fbd.svg`、GXW 及写入报告
- 将 GXW 文件导入 Web 工作台
- 以提案形式预览结果
- 校验后自动保存为版本化的本地产物
- 下载已保存的 GXW
- 经受控执行队列，在 GX Works2 中打开已批准的工程副本

当前可生成的模板包括：

- 常开触点
- 常闭触点
- 线圈
- 输入 / 输出终端
- `MOV`
- `TON`
- `TON_E`
- `CTU`
- `CTU_E`
- 已保存的部分 Function / Function Block ABI 模板

已有受控原生样例能够通过编译，并在 GX Works2 保存 / 重开后保持往返一致性。继电器串并联转换样例仍保留已知的 `C2034` 警告；该限制不会被隐藏。

当前重要限制包括：

- 不通用合成任意自定义库、结构体和未知 FB ABI
- 导入 GXW 的 CPU 识别尚不完整
- 未实现任意 IEC FBD 语义
- 多个独立梯形图块的编码规则尚未完全通用化
- 原生自动编译调用尚未完成
- FBD 仿真、诊断及 CSV 同步尚未接通

最新工程证据与适用边界见：

- [`docs/research/gxw_declarations_allocation_web_fbd_20260910.md`](docs/research/gxw_declarations_allocation_web_fbd_20260910.md)
- [`docs/research/gxw_project_write_pipeline_20260910.md`](docs/research/gxw_project_write_pipeline_20260910.md)

---

# GX Simulator2 测试

GXWorks Agent 可以根据当前 PLC 程序生成与版本绑定的仿真测试方案。

```text
PLC 程序
     ↓
AI 测试规划
     ↓
确定性的 Test DSL 规范化
     ↓
保存与版本绑定的方案
     ↓
操作员审批
     ↓
GX Simulator2 执行
     ↓
轨迹 + 断言
     ↓
保存证据
```

测试规划可以使用：

- I/O 映射
- 程序软元件
- Network 指令
- 读写依赖
- 执行触发条件
- 状态机
- 语义需求
- 部分静态分析发现

Test DSL 可以表示定时输入激励、预期结果、等待条件、不变量、轨迹采集软元件，以及支持的故障注入。

仿真仍属于**实验性能力**。真实 GX Simulator2 执行需要受支持的 Windows 环境及已安装的 Mitsubishi 软件。

仿真网关与真实 PLC 访问刻意隔离。

当前安全设计包括：

- 仅允许 localhost 通信
- 每进程独立认证
- 固定 GX Simulator2 目标
- 受控软元件写入
- 仿真网关不开放真实 PLC 连接路径

详见 [`simulator_gateway/README.md`](simulator_gateway/README.md)。

---

# 绑定证据的调试

失败的仿真记录可以转换为与版本绑定的调试方案。

当前调试工作流可以：

1. 加载对应的 PLC IR 和已保存的失败仿真记录。
2. 构建失败证据与反向依赖上下文。
3. 由诊断专项 Agent 分析证据。
4. 由补丁专项 Agent 提出局部 Network Patch。
5. 在任何执行之前校验并保存方案。
6. 执行调试操作前要求独立审批。

这样，诊断和修改始终关联到具体程序版本与失败证据，而不是仅依赖自由文本聊天描述。

全自动的 `compile → diagnose → repair → regression` 闭环尚未完成。

---

# FX3U 工程知识检索

GXWorks Agent 包含面向 FX3U 手册与工程知识的本地检索能力。

它可以辅助查询：

- PLC 指令
- 软元件约束
- 编程规则
- 故障排查信息

仓库在 [`benchmarks/`](benchmarks/) 中提供了 **220 个 Case 的检索 Benchmark**。

| 指标 | 结果 |
| --- | ---: |
| Cases | 220 |
| Recall@1 | 86.27% |
| Recall@5 | 98.04% |
| Recall@10 | 100% |
| MRR | 0.9033 |
| Negative accuracy | 100% |
| Mean latency | 58.2 ms |

当前报告：

[`benchmarks/fx3u_rag_benchmark_report.json`](benchmarks/fx3u_rag_benchmark_report.json)

> 这些是项目内部的检索指标，不代表端到端 PLC 程序正确率，也不代表真实设备上的安全性。

---

# Engineering Agent 与工具边界

GXWorks Agent 内置支持工具调用的 PLC 工程 Agent。

Agent 获得的是结构化工程工具，而不是不受限制的底层计算机控制能力。

典型工具包括：

```text
get_current_project
get_current_program_info
read_network
search_plc_manual
get_diagnostics
validate_project
compile_project
patch_program
validate_current_program
import_current_program_to_gxworks2
```

架构采用明确的分层：

```text
AI Agent
   ↓
Engineering Tools
   ↓
Tool Runtime
   ↓
PLC Core
   ├─ PLC IR
   ├─ Validator
   ├─ Knowledge Retrieval
   ├─ Session / Version Store
   └─ GX Works2 adapters
```

任意鼠标输入、不受限制的文件删除、真实 PLC 写入及不受限制的软元件强制操作，不会作为通用底层原语暴露给模型。

---

# MCP 集成

**MCP 是 GXWorks Agent 的一种外部接口，而不是整个项目的定位。**

独立 stdio MCP Server 提供高层工程工具，后端复用与内置 Agent 相同的 `ToolRuntime`。

```text
Built-in Agent ↔ ModelProvider
      │
      └──────────────────────────┐
                                 ↓
External MCP Client → MCP Server → ToolRuntime → PLC Core
```

目前支持两种 MCP 模式：

### 独立工作区模式

MCP Server 读取显式选定的工作区并提供工程工具，无需启动桌面 UI 或模型 Provider。

### Web 服务桥接模式

外部 MCP 客户端可以使用独立的 Agent token 连接正在运行的本地 Web 服务。

外部 Agent 不能修改审批模式，也不能绕过仅用户会话可用的设置接口。默认逐项审批时，外部 Agent 的候选仍需用户确认；选择替我审批或完全访问后，由 Web 后端按授权自动保存受支持的候选。仅完全访问会自动批准 GX 导入。独立 MCP 的原有边界不变。

详见 [`docs/integrations/mcp.md`](docs/integrations/mcp.md) 和 [`docs/integrations/web.md`](docs/integrations/web.md)。

---

# 模型支持

内置 Agent 使用与模型厂商无关的 `ModelProvider` 抽象。

当前内置配置支持：

| Provider | 状态 |
| --- | --- |
| 通过 OpenAI-compatible Transport 接入 DeepSeek | ✅ |
| 通过 OpenAI-compatible Transport 接入智谱 GLM | ✅ |
| 自定义 OpenAI-compatible API | ✅ |
| Anthropic 原生 API | 🚧 计划中 |
| Gemini 原生 API | 🚧 计划中 |

Codex 等支持 MCP 的外部 AI 客户端可以通过 MCP 接口使用 GXWorks Agent，无需将特定客户端绑定到 PLC 核心。

模型 Provider 与工程状态相互分离。程序版本、校验、审批和 GX 操作因此不依赖某一家 LLM 厂商。

---

# 安全与审批模型

GXWorks Agent 将通过校验的本地自动保存与外部执行分开处理。审批模式只决定后者是否需要逐项确认，不跳过程序校验，详见[审批模式](docs/architecture/approval-modes.md)。

| 审批动作 | 授权范围 | **不能**据此得出的结论 |
| --- | --- | --- |
| `accept_local` | 内部自动保存事务；旧草稿及默认外部 Agent 提案可显式保存 | 不包含 GX 导入、编译、仿真或 PLC 写入 |
| `gx_import` | 将 Ladder CSV 导入 GX Works2，或打开已批准的 GXW 副本 | 导入 / 打开成功不等于原生编译成功 |
| `simulation` | 执行已保存且与版本绑定的测试方案 | 只有已保存的实际执行证据才能作为运行结果 |
| `debug` | 执行与版本和证据绑定的调试方案 | 不能绕过候选哈希、版本绑定或回归检查 |

Web 后端通过专用执行协调器与跨进程桌面锁，串行处理真实 GX 桌面操作。

中断的外部操作会标记为中断，并要求操作员核对；服务重启后不会自动重放这些操作。

---

# 当前验证边界

仓库包含较广的自动化回归覆盖和受控 GXW 逆向实验，但部分集成能力仍需要在真实 Windows / Mitsubishi 软件环境中完成验证。

重要的待验收范围包括：

- 在受支持的实际使用环境中完成 GX Works2 导入 / 读取 / 同步的端到端验证
- 真实 GX Simulator2 执行及证据保存
- 调试回滚与回归行为
- 锁屏和 RDP 中断情形
- 普通用户的发布包启动交互
- 更广的 GXW / CPU / 指令覆盖
- FBD 仿真与诊断

离线测试通过不能替代这些真实环境验收。

当前验收矩阵见 [`docs/architecture/web-migration-checklist.md`](docs/architecture/web-migration-checklist.md)。

AI 生成或修改的程序在部署到真实设备前，仍应由具备相应经验的工程人员审查与验证。仿真不能替代真实设备调试、设备验收或功能安全设计。

---

# 项目结构

```text
src/                         PLC 核心、工作流、适配器与应用服务
web/                         React/Vite Web 工作台
simulator_gateway/           隔离的 GX Simulator2 网关
benchmarks/                  检索与 Agent 路由基准测试
packaging/pyinstaller/       PyInstaller 构建描述
requirements/                Web、MCP、Win7 与 GXW 测试专用依赖
docs/integrations/           Web、MCP、Codex 及集成文档
docs/architecture/           架构与迁移记录
docs/research/               GXW 逆向证据与研究结论
research/                    受控 GXW 模型、结果与证据辅助工具
scripts/                     启动、构建与发布辅助脚本
tests/                       确定性回归测试
tools/                       GXW 与工程实用工具
```

---

# 开发原则

项目当前遵循以下工程规则：

1. **LLM 推理不是工程事实的唯一依据。** 校验与应用状态由确定性代码管理。
2. **程序修改以版本化候选形式处理。** 外部副作用需要明确审批。
3. **保留未知 GXW 结构，而不是猜测其含义。** 原生生成仅覆盖有证据支持的布局与 ABI。
4. **仿真证据与真实 PLC 访问保持隔离。** 仿真网关不提供物理 PLC 路径。
5. **导入 / 打开成功不等于编译成功。** 状态报告区分这些阶段。
6. **不支持的程序明确失败。** 不会为了让 AI 工作流继续而静默放宽校验。

---

# 路线图

近期重点是完善已有工程闭环，而不是单纯增加更多 LLM 输出格式：

- 更丰富的交互式程序查看与依赖导航
- 更明确的问题—网络 / 问题—测试关联
- 可编辑的仿真方案与更清晰的轨迹可视化
- 原生 GXW 编译反馈与往返证据采集
- 扩展有证据支持的结构化梯形图 / FBD 范围
- FBD 仿真与诊断
- 更安全的真实设备观测及后续受控 PLC 集成
- GX Works3 适配器

---

# 许可证

本项目采用 [Apache License 2.0](LICENSE)。

Mitsubishi Electric、MELSEC、GX Works2、GX Works3、GX Simulator2 和 MX Component 是 Mitsubishi Electric Corporation 的商标或产品。本仓库与 Mitsubishi Electric 不存在隶属或官方认可关系，也不分发 Mitsubishi 专有软件。
