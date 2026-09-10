import { useEffect, useState } from "react";
import type { Job, Json } from "../api/client";
import { api } from "../api/client";
import { Button } from "../components/ui";

type Output = Record<string, Json>;

// Completion is a persisted job state, not a promise that a proposal exists.
// Fetch output after polling, reload and SSE completion alike. Do not depend on
// an SSE replay or the order in which project/proposal polling finishes.
export function useGenerationResult(job: Job | undefined, retry: number) {
  const [result, setResult] = useState<{
    id: string; value?: Output; error?: string;
  }>({ id: "" });
  const id = job?.kind === "generation" && job.status === "completed" ? job.id : "";
  useEffect(() => {
    let stopped = false;
    setResult({ id });
    if (id) void api<Output>(`/jobs/${encodeURIComponent(id)}/output`).then(
      (value) => { if (!stopped) setResult({ id, value }); },
      (error: Error) => { if (!stopped) setResult({ id, error: error.message }); },
    );
    return () => { stopped = true; };
  }, [id, retry]);
  const value = result.id === id ? result.value : undefined;
  const metadata = value?.generation && typeof value.generation === "object" && !Array.isArray(value.generation)
    ? value.generation as Output : undefined;
  const blocked = job?.result?.status === "contract_mismatch" || value?.status === "contract_mismatch" || !!metadata?.contract_mismatch;
  const proposalId = typeof value?.proposal_id === "string" ? value.proposal_id
    : typeof job?.result?.proposal_id === "string" ? job.result.proposal_id : "";
  const loading = !!id && !proposalId && !blocked && (!result.error || result.id !== id) && !value;
  return { id, value, metadata, blocked, proposalId, loading,
    error: result.id === id ? result.error : undefined };
}

export type GenerationResultState = ReturnType<typeof useGenerationResult>;

export function GenerationResult({ result, busy, onOpen, onRetry, onSpec, t }: {
  result: GenerationResultState;
  busy: boolean;
  onOpen: () => void;
  onRetry: () => void;
  onSpec: () => void;
  t: (key: string) => string;
}) {
  if (!result.id) return null;
  const mismatch = result.metadata?.contract_mismatch;
  const detail = mismatch && typeof mismatch === "object" && !Array.isArray(mismatch)
    ? mismatch as Output : undefined;
  return <section className="generation-result" aria-label={t("生成结果")}>
    {result.blocked ? <>
      <p className="error-text" role="status">{t("候选与确认方案冲突，未创建可接受的程序。")}</p>
      {typeof detail?.message === "string" && <p>{detail.message}</p>}
      {Array.isArray(detail?.issues) && <pre className="accepted-content">{detail.issues.map((v) => typeof v === "string" ? v : JSON.stringify(v)).join("\n")}</pre>}
      <p>{t("可以查看受阻候选及诊断；不能接受、导入或运行该候选。")}</p>
      <Button disabled={busy} onClick={onOpen}>{t("查看受阻候选")}</Button>{" "}
      <Button disabled={busy} onClick={onSpec}>{t("检查确认规格")}</Button>
    </> : result.proposalId ? <>
      <p>{t("候选已生成，查看预览后再人工接受。")}</p>
      <Button disabled={busy} onClick={onOpen}>{t("查看候选与校验")}</Button>
    </> : result.loading ? <p role="status">{t("正在读取生成结果")}</p> : <>
      <p className="error-text" role="alert">{t("任务已结束，但尚未取得可显示的候选结果。")}</p>
      <p>{t("请重试读取结果；不要重复调用模型或重新建立工程。")}</p>
    </>}
    <Button disabled={busy} onClick={onRetry}>{t("重新读取结果")}</Button>
  </section>;
}
