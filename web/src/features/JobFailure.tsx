import type { Job } from "../api/client";

const reasons: Record<string, string> = {
  latin_prose: "回复含有不符合所选语言的英文说明",
  japanese_script: "回复含有不符合所选语言的日文",
  non_english_script: "回复含有不符合所选语言的文字",
  unsupported_script: "回复含有不支持的语言文字",
  ambiguous_han_only: "无法确认回复是否为所选语言",
  invalid_json_object: "回复格式不完整或不是有效数据",
  invalid_prose_field: "说明字段格式错误",
  invalid_code_field: "程序字段格式错误",
  invalid_shared_input: "公共串联输入中不能包含并联块；请在分支输入中表达并联逻辑。",
  invalid_ladder_structure: "梯形图结构、指令或扫描语义未通过检查。",
  repair_base_invalid: "缺少可合并的完整候选，修复必须返回完整程序。",
  repair_identity_invalid: "梯级编号重复或无效，无法安全合并修复。",
  repair_shape_invalid: "修复响应的 JSON 结构不符合协议。",
  repair_scope_violation: "修复试图删除、新增或重排梯级，已阻止。",
  repair_no_progress: "修复未改变失败候选。",
};

const errorMessages: Record<string, string> = {
  model_timeout: "模型服务请求超时，请稍后重试。",
  model_authentication: "模型服务认证失败，请检查 API Key 和访问权限。",
  model_rate_limit: "模型服务请求过于频繁，请稍后重试。",
  model_invalid_request: "模型服务拒绝了请求，请检查模型配置和输入。",
  model_unavailable: "模型服务暂时不可用，请检查连接或稍后重试。",
  model_protocol: "模型未返回有效候选结果，请重试或更换模型。",
  model_provider_error: "模型服务调用失败，请检查配置或稍后重试。",
  generation_failed: "生成流程失败，确认规格和已有版本未被修改。",
};

export function JobFailure({ job, t }: { job: Job; t: (key: string) => string }) {
  if (!job.error_code) return null;
  if (job.error_code === "generation_validation_failed") return <div className="job-failure" role="alert">
    <p className="error-text">{t("梯形图候选未通过硬校验，未接受任何程序。")}</p>
    <p>{t("已执行结构修复")} {job.error_details?.attempt_count ?? 0}/{job.error_details?.max_attempts ?? 3}</p>
    {job.error_details?.violations?.map((violation, i) => <p key={i}>
      <code>{violation.path}</code><br /><span>{t(reasons[violation.reason] || "回复内容不符合要求")}</span>
    </p>)}
    <p className="muted">{t("确认规格仍然保留。请根据以上原因重试生成；不要重新建立工程。")}</p>
  </div>;
  if (job.error_code !== "response_rejected") return <p className="error-text">{t(errorMessages[job.error_code] || job.error_code)}</p>;
  return <div className="job-failure" role="alert">
    <p className="error-text">{t("模型回复未通过检查，请重试。")}</p>
    {job.error_details?.violations?.length ? <ul>
      {job.error_details.violations.map((violation, i) => <li key={i}>
        {t(violation.path.startsWith("reasoning") ? "思考内容" : violation.path.startsWith("tool_calls") ? "工具参数" : "回复内容")}：{t(reasons[violation.reason] || "回复内容不符合要求")}
      </li>)}
    </ul> : <p className="muted">{t("此历史任务未记录具体原因；新任务将显示检查详情。")}</p>}
  </div>;
}
