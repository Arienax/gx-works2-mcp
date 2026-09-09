import { useEffect, useState } from "react";
import { Plus, Check } from "lucide-react";
import type { Spec, Json } from "../api/client";
import { Button } from "../components/ui";
import { ChoiceInput } from "../components/ChoiceInput";

export function SpecEditor({
  value,
  t,
  disabled,
  onSave,
  onChange,
  issues,
}: {
  value: Spec | null;
  t: (key: string) => string;
  disabled: boolean;
  onSave: (spec: Spec) => void;
  onChange: (spec: Spec) => void;
  issues: { path: string; message: string }[];
}) {
  const [draft, setDraft] = useState<Spec | null>(value);
  const [raw, setRaw] = useState("");
  const [parseError, setParseError] = useState(false);
  const parseSpec = (text: string): Spec => {
    const parsed = JSON.parse(text);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
      throw new Error("Invalid specification");
    return parsed;
  };
  useEffect(() => {
    setDraft(value);
    setRaw(JSON.stringify(value, null, 2));
    setParseError(false);
  }, [value]);
  if (!draft)
    return <div className="panel-empty">{t("先分析需求以建立规格草稿。")}</div>;
  function patch(next: Spec) {
    setDraft(next);
    onChange(next);
    setRaw(JSON.stringify(next, null, 2));
    setParseError(false);
  }
  const approachId = (a?: Record<string, Json>) => String(a?.approach_id || a?.id || "");
  const rows = draft.io_table || [];
  const parameters = draft.parameters || [];
  return (
    <div className="spec-editor">
      <label>
        {t("需求摘要")}
        <textarea
          value={draft.summary || ""}
          onChange={(e) => patch({ ...draft, summary: e.target.value })}
        />
      </label>
      {(draft.approaches || []).length > 0 && (
        <label>
          {t("程序形式")}
          <select
            value={approachId(draft.selected_approach)}
            onChange={(e) =>
              patch({
                ...draft,
                selected_approach: draft.approaches?.find(
                  (p) => approachId(p) === e.target.value,
                ),
              })
            }
          >
            {draft.approaches?.map((a, i) => (
              <option key={approachId(a) || i} value={approachId(a)}>
                {String(a.name || a.title || approachId(a) || i + 1)}
              </option>
            ))}
          </select>
        </label>
      )}
      {!!draft.selected_approach?.description && <p className="approach-description">{String(draft.selected_approach.description)}</p>}
      {parameters.length > 0 && <div className="section-label">{t("确认问题")}</div>}
      {parameters.map((p, i) => (
        <ChoiceInput key={String(p.id || i)} t={t}
          label={String(p.question || p.label || p.name || p.id)}
          required={!!p.required && !p.required_when}
          hint={p.suggested_default ? `${t("建议值（待确认）")}：${String(p.suggested_default)}` : p.required_when ? t("根据相关选项确认") : undefined}
          error={issues.filter((issue) => issue.path.startsWith(`$.parameters[${i}]`)).map((issue) => issue.message).join("；")}
          value={String(p.value ?? "")}
          options={Array.isArray(p.options) ? p.options.filter((v): v is string => typeof v === "string" && !!v.trim()) : []}
          onChange={(value) => patch({ ...draft, parameters: parameters.map((v, j) => i === j ? { ...v, value, source: "user" } : v) })}
        />
      ))}
      <div className="section-label">
        {t("I/O 分配")}
        <Button
          variant="ghost"
          aria-label={t("新增 I/O")}
          onClick={() =>
            patch({
              ...draft,
              io_table: [...rows, { address: "", label: "", kind: "X" }],
            })
          }
        >
          <Plus size={14} />
        </Button>
      </div>
      {rows.map((row, i) => (
        <div className="io-row" key={i}>
          <input
            aria-label={`I/O ${i + 1}`}
            className="mono"
            value={String(row.address || "")}
            placeholder="X0"
            onChange={(e) =>
              patch({
                ...draft,
                io_table: rows.map((r, j) =>
                  i === j
                    ? {
                        ...r,
                        address: e.target.value.toUpperCase(),
                        kind: e.target.value.charAt(0).toUpperCase(),
                      }
                    : r,
                ),
              })
            }
          />
          <input
            aria-label={`${t("动作")} ${i + 1}`}
            value={String(row.purpose || row.description || row.label || "")}
            onChange={(e) =>
              patch({
                ...draft,
                io_table: rows.map((r, j) =>
                  i === j
                    ? {
                        ...r,
                        label: e.target.value,
                        purpose: e.target.value,
                        description: e.target.value,
                      }
                    : r,
                ),
              })
            }
          />
          <button
            className="text-button"
            aria-label={t("清除")}
            onClick={() =>
              patch({ ...draft, io_table: rows.filter((_, j) => i !== j) })
            }
          >
            ×
          </button>
        </div>
      ))}
      <label>
        {t("备注")}
        <textarea
          value={draft.user_notes || ""}
          onChange={(e) => patch({ ...draft, user_notes: e.target.value })}
        />
      </label>
      <details>
        <summary>{t("高级规格数据")}</summary>
        <textarea
          className="mono raw-editor"
          value={raw}
          onChange={(e) => {
            setRaw(e.target.value);
            try {
              parseSpec(e.target.value);
              setParseError(false);
            } catch {
              setParseError(true);
            }
          }}
          onBlur={() => {
            try {
              patch(parseSpec(raw));
            } catch {
              setParseError(true);
            }
          }}
        />
      </details>
      {issues.filter((issue) => !issue.path.startsWith("$.parameters[")).map((issue, i) => <p className="error-text" role="alert" key={i}>{issue.message}</p>)}
      {parseError && (
        <p role="alert" className="error-text">
          {t("规格数据不是有效 JSON 对象。")}
        </p>
      )}
      <Button
        variant="primary"
        disabled={disabled || parseError}
        onClick={() => {
          try {
            onSave(parseSpec(raw));
          } catch {
            setParseError(true);
          }
        }}
      >
        <Check size={15} />
        {t("确认规格")}
      </Button>
    </div>
  );
}
