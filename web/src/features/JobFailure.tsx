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
};

export function JobFailure({ job, t }: { job: Job; t: (key: string) => string }) {
  if (!job.error_code) return null;
  if (job.error_code !== "response_rejected") return <p className="error-text">{t(job.error_code)}</p>;
  return <div className="job-failure" role="alert">
    <p className="error-text">{t("模型回复未通过检查，请重试。")}</p>
    {job.error_details?.violations?.length ? <ul>
      {job.error_details.violations.map((violation, i) => <li key={i}>
        {t(violation.path.startsWith("reasoning") ? "思考内容" : violation.path.startsWith("tool_calls") ? "工具参数" : "回复内容")}：{t(reasons[violation.reason] || "回复内容不符合要求")}
      </li>)}
    </ul> : <p className="muted">{t("此历史任务未记录具体原因；新任务将显示检查详情。")}</p>}
  </div>;
}
