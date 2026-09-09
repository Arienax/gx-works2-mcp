import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Json, ModelSettings } from "../api/client";
import { Button, Badge } from "../components/ui";

type Profile = NonNullable<ModelSettings["profiles"]>[number] & {
  deletable?: boolean;
  generation_defaults?: Record<string, Json>;
  request_overrides?: Record<string, Json>;
};

export function Settings({
  value,
  t,
  onChange,
  disabled,
}: {
  value: ModelSettings;
  t: (s: string) => string;
  onChange: (settings: ModelSettings) => void;
  disabled: boolean;
}) {
  const [selected, setSelected] = useState(value.active_profile_id || "");
  const [creating, setCreating] = useState(false),
    [busy, setBusy] = useState(false);
  const [name, setName] = useState(""),
    [model, setModel] = useState(""),
    [baseUrl, setBaseUrl] = useState("");
  const [secret, setSecret] = useState(""),
    [capabilities, setCapabilities] = useState<Record<string, boolean>>({});
  const [defaults, setDefaults] = useState("{}"),
    [overrides, setOverrides] = useState("{}");
  const [error, setError] = useState(""),
    [message, setMessage] = useState("");
  const [deleting, setDeleting] = useState(false);
  const profile = value.profiles?.find((p) => p.id === selected) as
    | Profile
    | undefined;
  useEffect(() => {
    if (creating) return;
    setName(profile?.name || "");
    setModel(profile?.model || "");
    setBaseUrl(profile?.base_url || "");
    setSecret("");
    setCapabilities(profile?.capabilities || {});
    setDefaults(JSON.stringify(profile?.generation_defaults || {}, null, 2));
    setOverrides(JSON.stringify(profile?.request_overrides || {}, null, 2));
    setDeleting(false);
    // Background job refreshes must preserve in-progress fields and secrets.
  }, [selected, creating]);
  const parse = (text: string) => {
    const result = JSON.parse(text);
    if (!result || typeof result !== "object" || Array.isArray(result))
      throw new Error(t("配置数据必须是有效 JSON 对象。"));
    return result;
  };
  const command = () => ({
    ...(creating ? {} : { id: selected }),
    name,
    model,
    base_url: baseUrl,
    capabilities,
    generation_defaults: parse(defaults),
    request_overrides: parse(overrides),
  });
  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await action();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const ready =
    !busy && !disabled && !!name.trim() && !!model.trim() && !!baseUrl.trim();
  return (
    <div className="form settings-form">
      <div className="form-actions">
        <label>
          {t("选择模型配置")}
          <select
            disabled={busy}
            value={creating ? "" : selected}
            onChange={(e) => {
              setCreating(false);
              setSelected(e.target.value);
              setError("");
              setMessage("");
            }}
          >
            {creating && <option value="">{t("新建配置")}</option>}
            {value.profiles?.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <Button
          disabled={busy || disabled}
          onClick={() => {
            setCreating(true);
            setName("");
            setModel("");
            setBaseUrl("");
            setSecret("");
            setCapabilities({ tools: true, structured_output: true });
            setDefaults("{}");
            setOverrides("{}");
            setError("");
            setMessage("");
            setDeleting(false);
          }}
        >
          {t("新建配置")}
        </Button>
      </div>
      <label>
        {t("配置名称")}
        <input value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <label>
        {t("模型")}
        <input value={model} onChange={(e) => setModel(e.target.value)} />
      </label>
      <label>
        API URL
        <input
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          placeholder="https://api.example.com/v1"
        />
      </label>
      <label>
        API Key{" "}
        <Badge tone={!creating && profile?.configured ? "good" : "warn"}>
          {t(!creating && profile?.configured ? "已配置密钥" : "未配置密钥")}
        </Badge>
        <input
          type="password"
          autoComplete="new-password"
          placeholder={t("保留现有密钥")}
          value={secret}
          onChange={(e) => setSecret(e.target.value)}
        />
      </label>
      <p className="muted">{t("密钥仅保存到后端凭据存储。")}</p>
      <details>
        <summary>{t("模型能力与生成参数")}</summary>
        <div className="capability-grid">
          {[
            "reasoning",
            "tools",
            "structured_output",
            "multimodal",
            "tool_stream",
            "thinking_required",
            "disable_tool_choice_with_thinking",
          ].map((key) => (
            <label key={key}>
              <input
                type="checkbox"
                checked={!!capabilities[key]}
                onChange={(e) =>
                  setCapabilities((old) => ({
                    ...old,
                    [key]: e.target.checked,
                  }))
                }
              />
              {t(key)}
            </label>
          ))}
        </div>
        <label>
          {t("生成默认参数")}
          <textarea
            className="mono"
            aria-label={t("生成默认参数")}
            value={defaults}
            onChange={(e) => setDefaults(e.target.value)}
          />
        </label>
        <p className="muted">temperature · top_p · max_tokens</p>
        <label>
          {t("请求覆盖参数")}
          <textarea
            className="mono"
            aria-label={t("请求覆盖参数")}
            value={overrides}
            onChange={(e) => setOverrides(e.target.value)}
          />
        </label>
      </details>
      {error && (
        <p role="alert" className="error-text">
          {error}
        </p>
      )}
      {message && <p role="status">{message}</p>}
      <div className="form-actions">
        <Button
          variant="primary"
          disabled={!ready}
          onClick={() =>
            void run(async () => {
              const previous = new Set(value.profiles?.map((p) => p.id));
              const result = creating
                ? await api<ModelSettings>("/settings/profiles", "POST", {
                    ...command(),
                    ...(secret ? { api_key: secret } : {}),
                  })
                : await api<ModelSettings>("/settings", "PUT", {
                    active_profile_id: selected,
                    profile: command(),
                    ...(secret ? { api_key: secret } : {}),
                  });
              onChange(result);
              setSelected(
                creating
                  ? result.profiles?.find((p) => !previous.has(p.id))?.id ||
                      result.active_profile_id ||
                      ""
                  : selected,
              );
              setCreating(false);
              setSecret("");
              setMessage(t("设置已保存"));
            })
          }
        >
          {t(creating ? "创建配置" : "保存并使用")}
        </Button>
        <Button
          disabled={!ready || creating}
          onClick={() =>
            void run(async () => {
              const result = await api<{ status: string; message: string }>(
                `/settings/profiles/${encodeURIComponent(selected)}/test`,
                "POST",
                { profile: command(), ...(secret ? { api_key: secret } : {}) },
              );
              if (result.status === "connected") setMessage(t("连接成功"));
              else setError(result.message || t("连接失败"));
            })
          }
        >
          {t(busy ? "处理中…" : "测试连接")}
        </Button>
      </div>
      {!creating && (
        <div className="settings-danger">
          <Button
            variant="ghost"
            disabled={busy || disabled || !profile?.configured}
            onClick={() =>
              void run(async () => {
                onChange(
                  await api<ModelSettings>(
                    `/settings/profiles/${encodeURIComponent(selected)}/key`,
                    "DELETE",
                  ),
                );
                setSecret("");
                setMessage(t("密钥已清除"));
              })
            }
          >
            {t("清除已存密钥")}
          </Button>
          {profile?.deletable && (
            <Button
              variant="ghost"
              disabled={busy || disabled}
              onClick={() => setDeleting((v) => !v)}
            >
              {t("删除配置")}
            </Button>
          )}
          {deleting && (
            <div className="notice">
              <p>
                {t("删除此配置及其已存密钥？")} {profile?.name}
              </p>
              <Button
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    const result = await api<ModelSettings>(
                      `/settings/profiles/${encodeURIComponent(selected)}`,
                      "DELETE",
                    );
                    onChange(result);
                    setSelected(
                      result.active_profile_id ||
                        result.profiles?.[0]?.id ||
                        "",
                    );
                    setDeleting(false);
                    setMessage(t("配置已删除"));
                  })
                }
              >
                {t("确认删除")}
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
