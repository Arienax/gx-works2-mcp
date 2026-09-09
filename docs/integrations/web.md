# 本地 Web 工程工作台

Web 工作台通过本机 FastAPI 应用服务复用 `ToolRuntime`、PLC Core、生成/评审工作流和 SessionStore。浏览器显示后端生成的 SVG、ST、诊断和工程记录；它不实现 PLC 语义，不创建 Qt 窗口，也不通过 MCP 操作自身后端。

源码入口为 `python -m integrations.web`，仅监听 `127.0.0.1`，固定一个 Web worker。当前保留 Qt 主入口与桌面依赖。代码和离线回归可在没有 GX/MX 软件的环境检查；Windows 真实导入、仿真、桌面锁屏恢复与发布包验收仍须按[迁移核对表](../architecture/web-migration-checklist.md)单独执行。

## Windows 发布包：双击启动

1. 把整个 `GXWorks-Agent-Web` 目录解压到本机可读取的位置，不要只移动其中的 `.exe`。发布包无需另装 Python、Node.js 或 Qt。
2. 双击目录内的 `start-web.cmd`，选择工作区文件夹。已有工作区应选择包含 `index.json` 和 `projects` 的外层目录；新工程可以选择一个空文件夹。取消选择不会启动服务。
3. 在启动窗口输入 `1` 只读浏览或 `2` 工程编辑，直接回车默认只读。已有 Qt 正在编辑同一工作区时，先正常关闭 Qt 再选择工程编辑。
4. 服务准备好后，浏览器自动打开操作员登录页。若未自动打开，复制启动窗口中的 `Operator login` 本地链接到浏览器。使用期间保持启动窗口打开；结束时按 `Ctrl+C` 停止服务。

关闭浏览器不会停止服务。登录链接只供本机操作员使用，请勿分享。启动器默认使用端口 `8765`；已被占用时自动选择空闲的本机端口，并显示实际登录链接。启动或浏览项目不会自动运行 GX Works2、Simulator Gateway 或操作 PLC；导入及仿真仍需在工作台分别审批。

若启动窗口提示“源码环境尚未安装”，说明打开的是源代码目录，请完成下一节安装，或使用完整发布包。若提示工作区被占用，正常关闭原来的 Qt/Web 写入服务后再试。不要删除占用锁来绕过正在运行的任务。

## 源码启动

在仓库根目录建立 Python 3.10+ 环境，安装 Web 依赖，并用 Node.js 构建前端。Web 依赖与原 Win7/Qt 环境分开维护：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-web.txt
Push-Location web
npm ci
npm run build
Pop-Location
$env:PYTHONPATH = Join-Path (Get-Location) "src"
python -m integrations.web --workspace "D:\PLCWorkspaces\my-workspace" --port 8765 --open-browser
```

完成依赖安装和前端构建后，源码目录也可双击 `start-web.cmd`；它使用本目录的 `.venv`。命令行不带 `--open-browser` 时只输出登录链接，不打开浏览器。需要固定工作区或端口，也可调用 `scripts/start_web.ps1 -Workspace "D:\PLCWorkspaces\my-workspace" -Port 8765 -ReadOnly`；加 `-NoBrowser` 只显示链接。

启动后控制台会显示只供当前操作员使用的本地登录链接。令牌放在 URL fragment `#token=...`，登录后换为 HttpOnly、SameSite=Strict 的操作员会话。若需要固定启动凭据，可以提前设置 `PLC_WEB_OPERATOR_TOKEN`；不要把登录链接、模型密钥或令牌写入项目文件或提交到 Git。

旧工作区首次核对应使用：

```powershell
python -m integrations.web --workspace "D:\PLCWorkspaces\my-workspace" --read-only --port 8765
```

只读模式不启动任务管理器、提案写入或 GX 执行，不自动迁移旧版本。可写模式的任务、提案和暂存产物默认放在工作区父目录下的 `.gxworks-state/<workspace-hash>`，也可使用 `--state-dir` 指定工作区外的私有目录。工程索引、版本和已接受产物仍使用现有 SessionStore 格式。

一个工作区只有一个写入负责人。Qt 与 Web 不能同时以独立写入方打开同一工作区；切换入口前需等当前任务到达安全检查点并正常关闭。不要使用 Uvicorn 多 worker、热重载或 Windows 后台服务来运行真实 GX 操作。

## 操作与审批

项目和版本是工程状态的主入口。需求分析先形成可检查的规格，再确认并生成；生成任务保存候选提案，接受提案后才形成正式本地版本。候选并不意味着已经导入 GX 或通过仿真。

授权动作分别记录：

| 提案动作 | 获批准后执行的范围 | 不可推断的结论 |
| --- | --- | --- |
| `accept_local` | 接受冻结候选为本地版本 | 没有 GX 导入或 PLC 写入 |
| `gx_import` | 把指定当前版本的托管 CSV 导入 GX Works2 | 导入完成不等于原生编译或仿真通过 |
| `simulation` | 导入指定版本并运行指定已保存测试方案 | 环境不可用、未执行或执行错误不能显示通过 |
| `debug` | 执行指定版本和失败证据绑定的调试方案，沿用现有回归与回滚策略 | 不能绕过候选哈希、版本和仿真证据校验 |

批准时浏览器只提交提案 ID 和 `accept`/`reject`。后端重新检查活动版本、规格、候选与基础产物哈希；重复提交不会产生第二次执行。另一标签页改变版本或规格后，旧提案返回冲突。执行中进程退出会留下“中断，需要核对”的记录，重启不会自动再次导入或重复运行外部操作。

GX 导入、仿真和调试统一进入 `GXExecutionCoordinator` 固定单线程队列，COM 的初始化和释放发生在同一线程，桌面资源另有跨进程锁。旧 Qt 的导入、同步检查、拉取、仿真和调试入口使用同一资源锁。打开网页及环境查询只观察环境，不启动 Simulator Gateway。真实执行仍需要已登录且可交互的 Windows 桌面、GX Works2、GX Simulator2 和 MX Component。

显式的 GX 读取和同步检查也进入同一队列。同步检查返回已有基线与两侧程序的比较报告；读取沿用原生 CSV 解码和无损往返验证，仅形成可审查候选，接受本地版本仍需单独审批。Web 的只读调用关闭旧 GX 服务中默认的工程保存与基线写入，因此不会因为“检查”而保存 GX 工程或覆盖活动版本。空项目可先读取 GX 初始程序再审批接受。

原生程序如果含有本地语义目录尚未覆盖的 vendor 指令，Web 读取返回明确的 `unsupported`，不创建候选、不放宽 Agent/提案校验。原 Qt 的原生保真回读路径继续保留；这种程序不能据此视为已完成 Web 编辑/审批迁移。

## 任务与事件

`POST /api/jobs` 接受 `analysis`、`generation`、`agent`、`review`、`test_plan`、`debug_plan` 以及显式的 `gx_read`、`gx_inspect`，请求必须带幂等 `request_id`，返回持久任务 ID。提交时冻结项目、基础版本、确认规格、模型配置与响应语言，Provider/密钥仅留在后端运行上下文，不能进入任务 JSON。

刷新后读取 `GET /api/jobs/{job_id}` 与 `GET /api/jobs/{job_id}/output`；不要再次提交生成。通过 `GET /api/jobs/{job_id}/events?after=<sequence>` 或 `Last-Event-ID` 恢复 SSE。事件包括 `job_id`、`project_id`、`version_id`、`sequence`、`event_type`、`payload`。客户端按序号去重，完整保留已验收内容。模型文本经过 `collect_response` 的完整响应/语言验收才发布，不能把 Provider 原始 token 直接透传给浏览器。

任务取消是协作式安全检查点取消。等待执行的 GX Future 可取消；已经开始的外部操作不会因为页面关闭、网络断开或点击取消而被假装撤销。任务结束、产物构建成功、GX 导入成功和仿真通过是不同状态。

## 本地 HTTP 访问边界

服务校验 Host 和 Origin，不启用通配 CORS。操作员写操作需要会话、同源 Origin 与 `X-CSRF-Token`。Agent 路由使用单独的 Bearer token，操作员和 Agent token 不能相同。模型设置的读取只返回配置状态，不返回密钥；模拟器网关令牌也不进入浏览器。

项目、版本和产物使用受限 ID；下载接口通过登记产物定位文件，不接受任意本机路径。完整的受保护接口定义位于 `GET /api/openapi.json`。主要资源如下：

| 资源 | 接口 |
| --- | --- |
| 工程和版本 | `/api/projects`、`/api/projects/{project_id}/versions/{version_id}` |
| 程序、诊断与下载 | 版本资源下的 `/program`、`/diagnostics`、`/artifacts/{artifact_id}` |
| 任务与重连事件 | `/api/jobs`、`/api/jobs/{job_id}/events` |
| 提案预览和决定 | `/api/proposals/{proposal_id}/preview`、`/decision` |
| 设置与附件 | `/api/settings`、`/api/projects/{project_id}/attachments` |
| 需求形式的 SFC 输入 | `/api/sfc/requirement`，不代表 GX SFC 编译能力 |
| 环境观察 | `/api/environment`，不自动启动网关 |

## MCP 的显式服务连接模式

默认 stdio 仍是独立、无模型的只读工具适配器：创建候选和导入请求只返回 `confirmation_required`，不持久化版本或提案，不执行桌面操作。旧配置继续使用 `--workspace`，行为不变。

要把外部 Agent 的候选送到正在运行的 Web 后端，先给后端设置与操作员令牌不同的 `PLC_WEB_AGENT_TOKEN`，再显式启动桥接：

```powershell
# GXWORKS_MCP_AGENT_TOKEN 的值由本机凭据配置注入，应与后端
# PLC_WEB_AGENT_TOKEN 相同；它不是 PLC_WEB_OPERATOR_TOKEN。
$env:PYTHONPATH = Join-Path (Get-Location) "src"
python -m integrations.mcp --stdio `
  --service-url "http://127.0.0.1:8765" `
  --service-token-env GXWORKS_MCP_AGENT_TOKEN `
  --project PROJECT_ID
```

MCP 环境另需 `python -m pip install -r requirements-mcp.txt`。服务连接模式不需要本地 `--workspace`，也不推断浏览器当前选择；`--project` 必填，`--version` 可固定版本。只接受 loopback HTTP origin，拒绝重定向，令牌只从所指环境变量读取。

桥接只调用两个端点：`GET /api/agent/tools` 返回原注册表的 function schema；`POST /api/agent/tools/call` 提交 `{project_id, version_id?, name, arguments, call_id}`，返回完整公开 `data`、`content`、`is_error`，待确认时附上 `proposal_id`。后端仍经过共享 `ToolRuntime.invoke` 和安全工具白名单；`_candidate_ir`、`_confirmed_spec` 不外传。进程级 UUID 与每逻辑调用 UUID 防止 stdio 重启后的数字请求 ID 撞上历史幂等记录。Agent 只能提出候选，不能通过此连接审批或执行；操作员在 Web 看到同一后端保存的提案后决定。

## 开源 Agent 框架的取舍

本轮保留自有的确定性工作流与官方 MCP Python SDK。SDK 本身是 [MIT 许可](https://github.com/modelcontextprotocol/python-sdk/blob/main/LICENSE)，已承担 MCP 协议，无需再装一个 Agent 框架完成审批桥接。后续如果需要更丰富的模型工具编排，可在现有 `ModelProvider → ToolRuntime` 边界评估 [PydanticAI 的 MCP/toolset 接入](https://pydantic.dev/docs/ai/mcp/client/)；需要图式持久状态与中断恢复时，再评估 [LangGraph checkpoint](https://docs.langchain.com/oss/python/langgraph/persistence)。两者开源核心均为 MIT（[PydanticAI 许可](https://github.com/pydantic/pydantic-ai/blob/main/LICENSE)、[LangGraph 许可](https://github.com/langchain-ai/langgraph/blob/main/LICENSE)）。这是可插拔的后续选择，不能替代 ProposalService 的工程审批、不可自动重放 GX 副作用，也不能为框架另造一套 PLC 工具。免费开源不等于模型推理免费；更换框架不会自动减少模型 token、远程模型服务或本地算力的费用。

## 发布包

`web.spec` 打包独立 Web 入口，收录双击启动器、中英文 README、Web 指南、`web/dist`、默认安全配置、模型与指令资料、语言包、知识库及第三方声明，不收录用户 `config.json`、工作区、密钥或 Qt。原桌面打包入口和依赖继续保留。

已有网关二进制时：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_web_package.ps1 `
  -GatewayDirectory "C:\release-inputs\simulator-gateway"
```

网关目录必须包含 `PlcAi.GxSimulator2Gateway.exe`。仓库提供的是 C# 网关源码；如需构建，可使用现有 `tools/build_simulator_gateway.ps1` 在仓库外输出，再把其目录传给打包脚本。打包脚本不下载、不启动、不连接网关。没有网关时必须显式指定 `-AllowWithoutGateway`，该包不能据此声称具备已验收的真实仿真能力。

脚本会校验依赖与必须资源，运行 `npm ci`、前端构建，再调用 PyInstaller；`-SkipInstall` 使用已经安装的前端依赖，`-ValidateOnly` 只检查现有构建结果和资源。使用 `-Python` 和 `-NpmCommand` 可指定构建环境。输出目录为 `dist/GXWorks-Agent-Web`，普通用户双击其中的 `start-web.cmd`；命令行启动例如：

```powershell
.\dist\GXWorks-Agent-Web\GXWorks-Agent-Web.exe --workspace "D:\PLCWorkspaces\my-workspace" --port 8765 --open-browser
```

完整目录一起分发；模拟器网关位于可执行文件旁的 `simulator-gateway`。发布前按核对表检查实际包中的资源、登录、无 Qt 启动、旧工程只读和 Windows 实机工作流；PyInstaller 完成不等于实机验收完成。

### 正在使用发布包时准备更新

构建脚本不会停止正在运行的服务。若默认发布目录中的程序仍在使用，请加 `-StageName` 在仓库内生成独立更新包；暂存名称只能包含字母、数字、点、下划线和连字符，并以字母或数字开头。暂存模式拒绝覆盖已有同名包，也不允许输出路径经过目录联接或符号链接。

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_web_package.ps1 `
  -StageName "web-fix-20260910-01" -SkipInstall `
  -GatewayDirectory "C:\release-inputs\simulator-gateway"
python scripts/web_package_smoke.py `
  --package-dir "dist\staging\web-fix-20260910-01\GXWorks-Agent-Web" `
  --archive "build\staging\web-fix-20260910-01\web\PYZ-00.pyz"
```

加 `-ValidateOnly` 可只校验依赖、资源和目标路径，不构建、不启动，也不创建暂存目录。更新包验证完成后，再等待原服务任务停止并正常关闭服务，备份原发布目录后替换程序文件。原程序目录中的 `config.json` 是用户模型设置，应单独保留；Windows 凭据存储、工作区和原私有状态目录也必须保留，重启时继续使用相同工作区和 `--state-dir`（原来没有指定时仍不指定）。不要用清空目录或镜像删除方式更新正在使用的包。

构建机可运行 `python scripts/web_package_smoke.py`：该脚本校验发布资源与 Qt 排除项，只启动 Web 可执行文件，对临时空工作区执行只读登录/静态页面烟测，再关闭自己启动的进程。它不启动网关，也不调用 GX/MX。输出中的 `native_gx_not_tested=true` 必须保留为实际验收边界。
