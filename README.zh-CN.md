# GXWorks Agent

[English](README.md) | 简体中文

> **面向 Mitsubishi MELSEC PLC 开发的 AI 原生工程工作台与 Agent Runtime。**  
> 自然语言 → 已确认控制规格 → 共享生成上下文 → PLC IR → 确定性工程工作流 → GX Works2 / GXW → 仿真与验证证据。

![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)
![Platform](https://img.shields.io/badge/platform-Windows-0078D6.svg)
![PLC](https://img.shields.io/badge/demo-FX3U-orange.svg)
![Status](https://img.shields.io/badge/status-active%20development-yellow.svg)

<p align="center">
  <img src="resources/assets/demo.gif" alt="GXWorks Agent 演示" width="1200">
</p>

**GXWorks Agent** 是一个面向 Mitsubishi MELSEC PLC 开发的实验性 AI 原生工程工作台。它将自然语言编程、已确认工程规格、确定性程序处理、版本化工程状态、本地知识检索、仿真工作流、GX Works2 集成，以及供内置和外部 AI Agent 共用的工程 Tool Runtime 放在同一套系统中。

项目遵循一个核心原则：**LLM 输出本身不等于工程结果。** 模型负责提出程序和工程动作，应用负责工程状态、PLC IR 构建、结构验收、修改范围约束、版本管理、审批、证据以及外部副作用。

当前实现主要聚焦于 **FX3U + GX Works2**。Ladder CSV 工作流是目前最成熟的后端；原生 **GXW / 结构化梯形图 / FBD** 则仍属于基于证据持续推进的实验性方向。

---

## 快速开始

### 1. Windows Web 工作台

使用 Windows 发布包时，解压完整的 `GXWorks-Agent-Web` 目录，然后双击：

```text
start-web.cmd
```

选择工作区文件夹即可打开。直接生成和本地编辑在通过校验后会保存为带历史记录的版本。在 **设置 → 常规 → 操作审批** 中选择 **逐项审批**（默认）、**替我审批** 或 **完全访问**；这些模式控制已支持的 GX / 仿真 / 调试等外部执行，不会关闭 PLC 校验。切换完全访问需要明确确认。仍保留显式 `-ReadOnly` 恢复参数。

顶部统一提供 **导出文件、从 GX 读取、发送到 GX**、刷新 / 重绘和 **更多** 菜单。文件导出不需要连接 GX。

Web 发布包无需另行安装 Python、Node.js 或 Qt。启动工作台**不会**自动启动 GX Works2、GX Simulator2、仿真网关，也不会自动连接真实 PLC。

源码安装、审批边界、工作区锁、MCP 服务模式及 Windows 集成细节见 [Web 工作台使用指南](docs/integrations/web.md)。

### 2. 连接 Codex

GXWorks Agent 可以通过本机 MCP 工程接口，把当前选中的 PLC 工程直接暴露给 Codex App。Codex CLI 不是必需依赖。

1. 启动 GXWorks Agent Web 并打开一个 PLC 工程。
2. 进入 **设置 → 模型 → Integrations / MCP**。
3. 点击 **连接 Codex**。
4. 重启 Codex App，并新建一个任务。
5. 直接描述工程要求，例如：

```text
使用 gxworks 给当前工程生成一个三菱起保停程序：
X0 启动，X1 停止，Y0 电机，自锁。
```

Codex 使用的仍是与内置生成流程相同的当前工程、已确认规格、本地 PLC 知识检索、候选处理、PLC IR 构建和工程核心。**不需要安装 GXWorks 客户端 Skill**；MCP 是工程接口，可选的客户端 Prompt / Skill 只属于使用指导，不属于工程 Runtime。

详见 [Codex 集成](docs/integrations/codex.md) 和 [MCP 集成](docs/integrations/mcp.md)。

### 3. 源码安装

Web 源码版本先安装后端运行依赖，再使用根目录前端构建脚本：

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

保留的 Qt 开发入口仍可单独使用：

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

---

## 一套工程核心，多种 AI 入口

内置模型 Provider 和外部 Agent 都位于同一个工程层之上，而不是各自维护一套 PLC 实现。

```text
                 ┌─────────────────────────┐
                 │ 内置 ModelProvider      │
                 │ DeepSeek / compatible   │
                 └────────────┬────────────┘
                              │
外部 AI Agent                 │
Codex / MCP 客户端            │
          │                   │
          ▼                   ▼
        MCP          共享生成上下文
          │          Prompt / 规格 / RAG / 当前程序
          └──────────────┬───────────────┘
                         ▼
                   候选程序处理
             兼容 / 范围 / 结构验收
                         ▼
                       PLC IR
                         ▼
                 Tool Runtime / PLC Core
              ┌──────────┼───────────┐
              ▼          ▼           ▼
          GX Works2    仿真器      GXW / FBD
```

对于普通 Ladder 生成和编辑，内置 API 与外部 MCP 客户端共用同一套生成指令、已确认工程上下文、本地 RAG 策略、兼容性规范化、结构验收、PLC IR 构建和产物渲染。

这样可以避免再建立一套“仅 MCP 使用”的需求解释或校验规则。外部 Agent 负责模型规划；GXWorks Agent 继续负责确定性的工程状态与边界。

---

## 当前功能状态

| 领域 | 状态 |
| --- | --- |
| 自然语言需求分析与已确认控制规格 | ✅ 可用 |
| Ladder 生成、局部编辑、SVG 与 CSV 产物 | ✅ 可用 |
| PLC IR、结构验收、静态检查、Diff 与版本管理 | ✅ 可用 |
| Program Explorer、地址 / 注释搜索与引用跳转 | ✅ 可用 |
| 限定范围的程序修改与影响摘要 | ✅ 可用 |
| GX Works2 Ladder CSV 导入 / 导出与同步 | ✅ 可用 |
| FX3U 手册与工程知识检索 | ✅ 可用 |
| 本地 Web 工程工作台与持久化任务 | ✅ 可用 |
| 内置工程 Agent 与结构化 Tool Runtime | ✅ 可用 |
| 独立 MCP Server 与 Web 服务桥接 | ✅ 可用 |
| Codex App MCP 一键接入与真实客户端活动显示 | ✅ 可用 |
| 可编辑仿真工作台与测试方案工作流 | 🧪 实验性 |
| 问题 → 网络 → 测试追踪 | 🧪 实验性 |
| GX Simulator2 自动化执行与证据采集 | 🧪 实验性 |
| 绑定证据的调试规划与限定范围 Patch | 🧪 实验性 |
| 高级维护下的真实 PLC 只读观测 | 🧪 实验性 |
| GXW 工程检查与往返写入 | 🧪 实验性 |
| 结构化梯形图 / FBD 生成与编辑 | 🧪 实验性 |
| GXW 导入、预览、本地版本化、下载与受控打开 | 🧪 实验性 |
| Structured Text 生成 | 🧪 实验性 |
| 原生 GXW 自动编译命令 | 🚧 尚未完成 |
| FBD 仿真 / 诊断 | 🚧 尚未完成 |
| 完整任意 GXW / IEC FBD 支持 | 🚧 尚未完成 |
| GX Works3 适配器 | 📋 计划中 |
| 真实 PLC 写入路径 | 📋 当前 Web 工作流不开放 |

> 状态标记保持保守。“实验性”表示已有受控实现与测试证据，并不代表已经成为适用于任意 PLC 程序、GX 版本或 CPU 型号的通用生产级后端。

---

## 为什么需要 GXWorks Agent

传统 LLM 工作流往往停留在：

```text
Prompt
  ↓
LLM
  ↓
PLC 代码
```

GXWorks Agent 则维护明确的工程闭环：

```text
自然语言需求
      ↓
需求分析
      ↓
已确认控制规格
      ↓
共享生成上下文
      ↓
候选程序
      ↓
结构验收 / PLC IR
      ↓
版本化工程 + Diff
   ┌──────┼────────┐
   ▼      ▼        ▼
 评审    仿真    GX Works2 / GXW
   │      │        │
   └────── 工程证据 ──────┘
```

项目目标不是用聊天记录取代工程状态。LLM 仍用于需求理解、规划、评审和诊断，但工程状态与执行边界由确定性的应用代码管理。

---

## 示例

直接描述所需设备控制行为：

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

分析阶段可以把这段需求转换为**可审查的控制规格**，包含编程方案、待确认问题、参数和 I/O 分配。规格确认后才进入生成流程。

---

# Web 工程工作台

当前 Web 前端采用 React/Vite，后端由 FastAPI 提供服务。PLC 语义仍由 Python 工程核心负责；浏览器是操作员界面，不重复实现 PLC 逻辑。

工作台目前提供：

- 项目与版本导航
- 梯形图、FBD、ST、诊断、评审、仿真和交付视图
- 自然语言分析 / 生成 / Agent 任务
- 可编辑的已确认控制规格
- 持久化任务进度及支持断线续读的事件历史
- Program Explorer：Network 选择、地址 / 注释搜索、读写引用跳转、缩放与无模型重绘
- 限定范围修改与受影响 Network / 软元件摘要
- 与报告、Network、证据、复现测试绑定的问题卡片
- 可编辑的版本绑定仿真方案和运行回放
- 候选提案审查与 Diff 查看
- 校验通过后自动保存本地版本；GX 导入、仿真和调试按工作区审批模式执行
- GXW 导入与 FBD 编辑
- 模型配置、Codex/MCP 接入、服务检查与真实 MCP 客户端调用状态
- 限定站号 / 地址 / 适配器范围的高级真实 PLC 只读观测
- 可阅读的工程交付摘要

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

用户在生成前确认规格。之后生成的候选与已确认工程上下文以及项目 / 版本状态绑定。

这用于减少 AI 生成 PLC 程序时的一类常见问题：面对不完整控制要求时，生成语法看似合理、实际行为却不符合预期的逻辑。

---

# 共享生成上下文与候选处理链

内置 API 与外部 MCP 客户端共用一个与模型无关的生成层。

`get_generation_context` 可以向外部 Agent 提供完成工程任务所需的公开工程投影：

- 当前选中的工程与 PLC 型号
- 已确认控制规格
- 编辑时的当前 Ladder 程序
- 生成指令与输出纪律
- 与内置 API 相同检索策略下的本地 RAG 证据
- 支持的候选输出协议

普通首次生成和编辑最终都收敛到同一条候选处理链：

```text
内置模型响应 或 外部 Agent 候选
                    ↓
              兼容性规范化
                    ↓
          full / partial 编辑组装
                    ↓
          结构与地址范围验收
                    ↓
          保守的条件结构整理
                    ↓
                  PLC IR
                    ↓
        JSON / ST / SVG / CSV 产物
```

确认规格后的普通生成不存在隐藏的语义重生成循环。结构不合法的候选会直接返回诊断；明确的 Debug / repair 仍属于独立的限定范围工作流。

兼容层会先把已支持的旧表示转换到统一形式，再进行验收，避免“等价表示不同”被误判为模型错误；但它不会让不支持的指令或非法软元件绕过 PLC 指令 / 地址检查。

---

# PLC 中间表示

内部 **PLC IR（PLC Intermediate Representation）** 是模型输出与工程操作之间的语义层。

```text
                    ┌─ Ladder CSV
                    ├─ Structured Text
AI → PLC IR ────────┼─ SVG 预览
                    ├─ 静态检查
                    ├─ Diff / 修改范围分析
                    ├─ 测试规划
                    └─ GX Works2 适配器
```

PLC IR 表示 Network、PLC 指令、软元件、定时器 / 计数器、读写关系、执行触发条件、修订版本、静态分析发现、I/O 映射、语义需求以及可确定性渲染的程序状态。

因此，每个工程操作都不需要模型把整个工程重新生成为自由文本。

---

# 程序查看、编辑与版本管理

普通编辑与首次生成共用候选处理链，而不是进入另一套修复引擎。已有程序可以通过紧凑的 `partial` 响应完成修改，只返回修改 / 新增的完整梯级、确实变化的注释和明确删除项。

```text
当前程序
      ↓
修改要求
      ↓
共享生成上下文
      ↓
Partial 候选
      ↓
结构验收
      ↓
Diff / 修改摘要
      ↓
历史版本
```

例如：

```text
把停止逻辑改成停止优先。
不要修改其他 Network。
```

明确且有证据范围的 Debug 工作流不同：`read_network → patch_program` 保留更严格的 Network / 地址范围约束，不作为普通编辑的默认路径。

保存为本地版本**不代表**程序已经导入 GX Works2、通过原生编译、完成仿真或在真实 PLC 上执行。

---

# 校验、评审与证据边界

GXWorks Agent 明确区分不同层级的证据：

1. **结构验收** —— 候选可以被系统安全表示和处理。
2. **PLC IR 一致性** —— 确定性的内部表示在自身结构上有效。
3. **静态工程评审** —— 本地分析器和可选 AI Reviewer 提供风险与问题报告。
4. **行为验证** —— 具体输入序列、时序与结果经过实际测试或仿真执行。
5. **原生 / 硬件验证** —— GX Works2、GX Simulator2 或真实目标确实执行了对应操作。

通过前一层**绝不会**被报告为已经通过后一层。

评审流程可以检查结构有效性、软元件和地址、指令约束、定时器 / 计数器结构、I/O 引用、读写依赖、多处写入、自锁 / 复位归属、状态行为、时序路径及其他常见 Ladder 风险。可选 AI 专项评审可以补充解释，但不会覆盖确定性检查结果。

```text
候选程序
   ↓
本地确定性检查
   ↓
可选 AI 专项评审
   ↓
与版本绑定的证据报告
```

---

# GX Works2 梯形图集成

目前最成熟的 GX Works2 后端仍是 **Ladder CSV 导入 / 导出工作流**。

当前能力包括：

- Ladder CSV 与软元件注释 CSV 生成
- GX Works2 导入 / 导出
- 程序与注释同步
- 覆盖前自动备份
- 同步基线
- 外部人工修改检测
- 冲突保护
- 可选往返验证

如果 GXWorks Agent 检测到 GX Works2 中的程序在上一次同步基线后被人工修改，会停止操作，而不是静默覆盖工程人员的修改。

部分 GX Works2 操作仍依赖 GUI 自动化，因此会受到 GX 版本、界面语言、桌面状态和 Windows 会话条件影响。

---

# 原生 GXW / 结构化梯形图 / FBD 工作流

GXWorks Agent 已包含面向 GX Works2 结构化梯形图 / FBD 的实验性**原生 GXW 工程处理流程**。

该能力建立在逆向研究和受控的编译 / 保存 / 重开实验之上。未知结构优先保留而不是猜测；生成范围限定在具有可重复证据的布局和 ABI 上。

当前流程可以检查选定的 `Program.pou` 记录、保留其他和未知记录、生成已支持的 FX3U 结构化梯形图 / FBD 对象与连线、编辑已知声明、同步已支持 FB 的实例声明、扩展必要的 CFB 分配、更新已知 GXW 元数据、生成 FBD / GXW 产物与写入报告，并支持导入 Web 工作台、预览、版本化、下载和通过受控 GX 执行队列打开已批准副本。

当前可生成模板包括常开 / 常闭触点、线圈、终端、`MOV`、`TON`、`TON_E`、`CTU`、`CTU_E`，以及部分已保存 Function / Function Block ABI 模板。

当前重要限制包括：

- 不通用合成任意自定义库、结构体和未知 FB ABI
- 导入 GXW 的 CPU 识别尚不完整
- 未实现任意 IEC FBD 语义
- 多个独立梯形图块的编码规则尚未完全通用化
- 原生自动编译调用尚未完成
- FBD 仿真、诊断及 CSV 同步尚未接通

工程证据与当前边界见：

- [`docs/research/gxw_declarations_allocation_web_fbd_20260910.md`](docs/research/gxw_declarations_allocation_web_fbd_20260910.md)
- [`docs/research/gxw_project_write_pipeline_20260910.md`](docs/research/gxw_project_write_pipeline_20260910.md)

---

# GX Simulator2 测试与绑定证据的调试

GXWorks Agent 可以根据当前 PLC 程序构建与版本绑定的仿真测试方案。可编辑仿真工作台可以表示初始输入、定时激励、预期结果、等待条件、不变量、轨迹采集软元件、受支持的故障注入，以及需求 / 问题关联。

```text
PLC 程序
     ↓
AI / 操作员测试规划
     ↓
确定性的 Test DSL
     ↓
保存并绑定版本的方案
     ↓
经审批执行
     ↓
GX Simulator2
     ↓
轨迹 + 断言 + 已保存证据
```

失败的实际运行可以进入绑定证据的调试工作流：加载精确程序版本和失败证据、生成诊断、提出限定范围 Patch、校验调试方案，并在执行前遵循当前审批策略。

全自动的 `compile → diagnose → repair → regression` 闭环尚未完成。真实 GX Simulator2 执行需要受支持的 Windows 环境及已安装的 Mitsubishi 软件。

仿真网关与真实 PLC 访问保持隔离。详见 [`simulator_gateway/README.md`](simulator_gateway/README.md)。

---

# FX3U 工程知识检索

GXWorks Agent 包含面向 FX3U 手册与工程知识的本地检索能力。

检索逻辑针对 PLC 指令做了专门处理：Mitsubishi 助记符、`AND<>` 等比较指令族、`MPS/MRD/MPP` 等堆栈指令、软元件地址、手册章节标题、PLC 型号范围和任务范围都会作为工程检索信号处理，而不是简单按普通文本分词。

它可以辅助查询 PLC 指令、软元件约束、编程规则和故障排查信息。内置生成路径与外部 Agent 均可通过相同检索策略使用这些内容，外部入口为 `get_generation_context` / `search_plc_manual`。

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

当前报告：[`benchmarks/fx3u_rag_benchmark_report.json`](benchmarks/fx3u_rag_benchmark_report.json)

> 这些是项目内部的检索指标，不代表端到端 PLC 程序正确率，也不代表真实设备上的安全性。

---

# 外部 AI Agent 与 MCP

**MCP 是 GXWorks Agent 的外部工程接口，而不是整个项目本身的定位。** 外部客户端不会获得一套简化或独立的 PLC 后端。

外部 Agent 可以使用与内置工程流程相同的当前工程、已确认规格、当前程序、本地知识检索、候选处理、PLC IR 构建、版本状态和审批边界。

普通生成 / 编辑流程为：

```text
get_current_project
        ↓
get_generation_context(user_requirement=...)
        ↓
Agent 规划 full / partial Ladder 候选
        ↓
search_plc_manual（仍有具体事实需要查证时）
        ↓
create_program_candidate
```

MCP Server 初始化指导会明确要求客户端不要扫描源码仓库，也不要通过手写 CSV / GXW 绕过工程工具。

工作台分别显示**连接配置**、**MCP 服务检查**和**真实客户端工程工具调用**。`tools/list` 成功或 launcher 探测通过，不会被误报为“Codex 已经实际使用工程工具”。

目前保留两种部署模式：

### Web 服务桥接

推荐用于本机产品使用。Codex 或其他已授权 MCP 客户端连接正在运行的 Web 工作台，共享其当前选中工程和审批策略。

### 独立工作区模式

适用于 CI、隔离测试和无界面集成。它针对显式选定的工作区暴露高层工程工具，无需启动 Web UI 或模型 Provider。

外部 Agent 不能修改审批模式，不能自行批准待处理提案，也不能绕过仅操作员可用的接口。连接 MCP 不需要安装客户端 Skill。

详见 [`docs/integrations/codex.md`](docs/integrations/codex.md)、[`docs/integrations/mcp.md`](docs/integrations/mcp.md) 和 [`docs/integrations/web.md`](docs/integrations/web.md)。

---

# 工程工具边界

代表性工具按用途分组如下：

```text
工程上下文
  get_current_project
  get_generation_context

程序创建 / 普通编辑
  create_program_candidate

查看与诊断
  get_current_program_info
  read_network
  get_diagnostics

工程知识
  search_plc_manual

明确的限定范围 Debug / repair
  patch_program

校验 / 集成
  validate_project
  compile_project
  validate_current_program
  import_current_program_to_gxworks2
```

模型获得的是结构化工程工具，而不是不受限制的底层计算机控制能力。任意鼠标输入、不受限制的文件删除、真实 PLC 写入及不受限制的软元件强制操作，不会作为通用 Agent 原语暴露给模型。

---

# 模型支持

内置 Agent 使用与模型厂商无关的 `ModelProvider` 抽象。

| Provider | 状态 |
| --- | --- |
| 通过 OpenAI-compatible Transport 接入 DeepSeek | ✅ |
| 通过 OpenAI-compatible Transport 接入智谱 GLM | ✅ |
| 自定义 OpenAI-compatible API | ✅ |
| Anthropic 原生 API | 🚧 计划中 |
| Gemini 原生 API | 🚧 计划中 |

Codex 等支持 MCP 的外部 AI 客户端可以使用 GXWorks Agent，而不需要把特定客户端写入 PLC 核心。模型 Provider 与工程状态相互分离，因此程序版本、校验、审批和 GX 操作不依赖某一家 LLM 厂商。

---

# 安全与审批模型

GXWorks Agent 将通过校验的本地程序状态与外部执行分开处理。工作区审批模式只控制已支持的外部动作，不会绕过 PLC 校验。详见[审批模式](docs/architecture/approval-modes.md)。

| 审批动作 | 授权范围 | **不能**据此得出的结论 |
| --- | --- | --- |
| `accept_local` | 将冻结候选保存为本地版本 | 不包含 GX 导入、编译、仿真或 PLC 写入 |
| `gx_import` | 将 Ladder CSV 导入 GX Works2，或打开已批准的 GXW 副本 | 导入 / 打开成功不等于原生编译成功 |
| `simulation` | 执行已保存且与版本绑定的测试方案 | 只有已保存的实际执行证据才能作为运行结果 |
| `debug` | 执行与版本和证据绑定的调试方案 | 不能绕过候选哈希、版本绑定或回归检查 |

Web 后端通过专用执行协调器与跨进程桌面锁串行处理真实 GX 桌面操作。中断的外部操作会标记为中断并要求操作员核对，服务重启后不会静默重放。

真实 PLC 只读观测与写入 / 强制 / CPU 控制能力刻意分离，并受配置的站号、地址范围、有效期和适配器身份约束。

---

# 当前验证边界

仓库包含较广的自动化回归覆盖和受控 GXW 逆向实验，但部分结论仍需要真实 Windows / Mitsubishi 软件环境中的证据。

重要待验收范围包括：

- 在更多受支持实际环境中完成 GX Works2 导入 / 读取 / 同步端到端验证
- 对更多程序进行真实 GX Simulator2 执行与证据保存
- 原生 GXW 编译反馈与更广往返覆盖
- 调试回滚与回归行为
- 锁屏和 RDP 中断情形
- 更广的 GXW / CPU / 指令覆盖
- FBD 仿真与诊断
- 任何未来受控的真实 PLC 写入路径

离线测试、结构验收、静态分析或生成产物都不能替代原生执行证据和真实设备验证。

当前验收记录与边界见 [`docs/architecture/workbench-roadmap-acceptance.md`](docs/architecture/workbench-roadmap-acceptance.md) 和 [`docs/architecture/web-migration-checklist.md`](docs/architecture/web-migration-checklist.md)。

---

# 项目结构

```text
src/                         PLC 核心、工作流、适配器与应用服务
web/                         React/Vite Web 工作台
hardware_reader/             受限的真实 PLC 只读观测辅助程序
simulator_gateway/           隔离的 GX Simulator2 网关
benchmarks/                  检索与 Agent 路由基准测试
packaging/pyinstaller/       PyInstaller 构建描述
requirements/                Web、MCP、Win7 与 GXW 测试专用依赖
docs/integrations/           Web、MCP、Codex 及集成文档
docs/architecture/           架构、迁移与验收记录
docs/research/               GXW 逆向证据与研究结论
research/                    受控 GXW 模型、结果与证据辅助工具
scripts/                     启动、构建、验收与发布辅助脚本
tests/                       确定性回归测试
tools/                       GXW 与工程实用工具
```

---

# 开发原则

1. **LLM 推理不是工程证明。** 工程状态和验收边界由确定性的应用代码管理。
2. **内置 Agent 与外部 Agent 共用工程核心。** MCP 不引入第二套 PLC 生成规则。
3. **普通编辑走生成候选链。** 严格的 `patch_program` 仅保留给明确、限定范围的 Debug / repair。
4. **保留未知 GXW 结构，而不是猜测其含义。** 原生生成仅覆盖有证据支持的布局和 ABI。
5. **仿真证据与真实 PLC 访问保持隔离。** 仿真网关不提供物理 PLC 路径。
6. **导入 / 打开、结构验收、仿真、原生编译和硬件执行是不同层级的结论。** 状态报告必须区分这些阶段。
7. **不支持的程序明确失败。** 不会为了让 AI 工作流继续而静默放宽工程边界。

---

# 路线图

近期重点是完善共享工程闭环，而不是继续增加互相独立的模型集成：

- 扩展程序查看与依赖导航能力
- 强化问题 → Network → 测试追踪
- 更丰富的可编辑仿真方案与轨迹可视化
- 原生 GXW 编译反馈与往返证据采集
- 扩展有证据支持的结构化梯形图 / FBD 范围
- FBD 仿真与诊断
- 更安全的真实设备观测及后续受控 PLC 集成
- 基于共享 MCP / ToolRuntime 边界接入更多外部 Agent
- GX Works3 适配器

---

# 许可证

本项目采用 [Apache License 2.0](LICENSE)。

Mitsubishi Electric、MELSEC、GX Works2、GX Works3、GX Simulator2 和 MX Component 是 Mitsubishi Electric Corporation 的商标或产品。本仓库与 Mitsubishi Electric 不存在隶属或官方认可关系，也不分发 Mitsubishi 专有软件。
