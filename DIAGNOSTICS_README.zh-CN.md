# 运行错误诊断测试版

此版本基于已有的 context-policy 测试版，只增加日志和下载入口。
不修改模型提示词策略、响应验收条件、自动修复或重试预算、PLC 校验和审批。

## 收集一次真实错误

解压完整新发布包到新目录，正常运行 start-adaptive.cmd 或 start-legacy.cmd。
使用相同模型和确认规格重现一次错误，然后点击报错下方的「下载错误诊断日志」。
下载得到 gxworks-diagnostics-job_xxx.zip；检查后再分享，不会自动上传。
无需导出整个工作区，无需安装 Python，无需运行管理员终端。

## 包内内容

- summary.json：任务编号、任务类型/状态、已有错误码、构建提交；不含任务输入。
- diagnostics.jsonl：按时间记录模型请求序号、流式/非流式、实际 response_format 和长度上限（仅服务明确配置时）、正文/推理字符数、返回类型、结束原因、用量（仅服务提供时）、JSON 解析行列、异常类型及堆栈中的文件/函数/行号。
- README.txt：字段解释。

日志不保存 API Key、Authorization、URL、完整异常消息、源码行、局部变量、提示词、模型回复正文或推理正文。异常堆栈只保存代码位置。
没有服务端 finish_reason 时记录 unknown/finish_seen=false，不据此猜测截断。
content_chars=0 与 reasoning_chars>0 能表明只有推理没有正文，但不能独立证明原因。
JSON 的 line/column 是剥离现有允许的外层代码围栏后的解析位置；original_* 是原回复中的位置。

日志存放在当前应用状态目录 diagnostics/job_xxx.jsonl，每个任务上限 512 KiB。
应用默认状态在工作区外层的 .gxworks-state/<工作区摘要>/ 下；不写入 PLC 工程目录。
旧任务没有新诊断记录时导出标记 not_captured，不会伪造结束原因或原始回复。
运行中的任务也可能只有部分记录，排障应优先导出已经失败的任务。

该包的测试只证明日志机制和软件流程；尚未复现使用者的真实模型错误，也不代表错误已修复。
这些元数据能缩小故障范围，但无法替代所有情况下对脱敏原始回复的进一步检查。
