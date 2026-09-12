import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Json, ModelSettings } from "../api/client";
import { Button, Badge } from "../components/ui";

type Profile = NonNullable<ModelSettings["profiles"]>[number] & {
  deletable?: boolean;
  generation_defaults?: Record<string, Json>;
  request_overrides?: Record<string, Json>;
};

type Discovery = {
  kind: "model_discovery_v1";
  models?: string[];
  recommended_model?: string | null;
  selected_model_available?: boolean;
  capabilities?: Record<string, boolean>;
  detected?: string[];
  note?: string;
};

type McpStatus = {
  service_url?: string;
  project_id?: string;
  bound_project_id?: string | null;
  credential_ready?: boolean;
  launcher_ready?: boolean;
  codex_cli_available?: boolean;
  codex_command?: string | null;
};

type McpResult = {
  status?: string;
  message?: string;
  project_id?: string;
  tool_count?: number;
  codex_connected?: boolean;
  replaced_existing?: boolean;
};

const currentProjectId = () =>
  new URLSearchParams(window.location.search).get("project") || "";

function parseDiscovery(message: string): Discovery | null {
  try {
    const value = JSON.parse(message) as Discovery;
    return value?.kind === "model_discovery_v1" ? value : null;
  } catch {
    return null;
  }
}

function McpIntegrations({
  t,
  disabled,
}: {
  t: (s: string) => string;
  disabled: boolean;
}) {
  const projectId = currentProjectId();
  const [status, setStatus] = useState<McpStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const refresh = async () => {
    if (!projectId) {
      setStatus(null);
      return;
    }
    const value = await api<McpStatus>(
      `/integrations/mcp?project_id=${encodeURIComponent(projectId)}`,
    );
    setStatus(value);
  };

  useEffect(() => {
    let stopped = false;
    if (!projectId) return;
    api<McpStatus>(`/integrations/mcp?project_id=${encodeURIComponent(projectId)}`)
      .then((value) => !stopped && setStatus(value))
      .catch((e) => !stopped && setError((e as Error).message));
    return () => {
      stopped = true;
    };
  }, [projectId]);

  const run = async (path: string) => {
    if (!projectId || busy || disabled) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await api<McpResult>(path, "POST", { project_id: projectId });
      if (result.status === "failed") throw new Error(result.message || t("连接失败"));
      setMessage(result.message || t("连接成功"));
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const manualConfig = `[mcp_servers.gxworks]\ncommand = "gxworks-agent-mcp"\nstartup_timeout_sec = 30\ntool_timeout_sec = 120`;

  return (
    <div className="form settings-form">
      <div className="notice">
        <strong>GXWorks Agent MCP</strong>
        <p>
          {t("Web 会把 MCP 服务地址和独立 Agent 凭据保存到 Windows Credential Manager。连接完成后，Codex 只需启动本机 launcher，不再需要复制 token、service-url 或工程 ID。")}
        </p>
      </div>

      <div className="context-chips">
        <Badge tone={status?.credential_ready ? "good" : "warn"}>
          {t(status?.credential_ready ? "本机凭据已就绪" : "本机凭据未就绪")}
        </Badge>
        <Badge tone={status?.launcher_ready ? "good" : "warn"}>
          {t(status?.launcher_ready ? "MCP launcher 已就绪" : "MCP launcher 不可用")}
        </Badge>
        <Badge tone={status?.codex_cli_available ? "good" : "warn"}>
          {t(status?.codex_cli_available ? "已检测到 Codex" : "未检测到 Codex CLI")}
        </Badge>
      </div>

      <label>
        {t("当前工程")}
        <input readOnly value={projectId || t("未选择工程")} />
      </label>
      <label>
        Service URL
        <input readOnly value={status?.service_url || window.location.origin} />
      </label>
      {status?.bound_project_id && (
        <p className="muted">
          {t("MCP 当前绑定工程")}: <span className="mono">{status.bound_project_id}</span>
        </p>
      )}

      <div className="form-actions">
        <Button
          variant="primary"
          disabled={!projectId || busy || disabled || !status?.credential_ready || !status?.launcher_ready}
          onClick={() => void run("/integrations/mcp/codex/connect")}
        >
          {t(busy ? "处理中…" : "连接 Codex")}
        </Button>
        <Button
          disabled={!projectId || busy || disabled || !status?.credential_ready || !status?.launcher_ready}
          onClick={() => void run("/integrations/mcp/test")}
        >
          {t("测试 MCP 连接")}
        </Button>
      </div>

      {!status?.credential_ready && (
        <p className="muted">
          {t("请先用当前版本重新启动 Web 工作台。启动器会自动生成并保存 MCP Agent 凭据，不再在终端要求手工复制 token。")}
        </p>
      )}
      {message && <p role="status">{message}</p>}
      {error && <p role="alert" className="error-text">{error}</p>}

      <div className="notice">
        <strong>{t("连接后怎么用")}</strong>
        <p>{t("以后在 Codex 中直接说“用 gxworks 给当前工程生成起保停”即可。不要再把 MCP 配置粘贴给模型，也不需要让模型读取本仓库来研究接入方式。")}</p>
      </div>

      <details>
        <summary>{t("Advanced / 其他 MCP 客户端")}</summary>
        <p className="muted">
          {t("Claude/Cursor 等客户端也可以直接启动同一个 launcher。先点击“测试 MCP 连接”绑定当前工程；正常 Windows 使用不需要 env、service-url、PYTHONPATH 或 python -m integrations.mcp。")}
        </p>
        <pre className="mono">{manualConfig}</pre>
        <Button onClick={() => void navigator.clipboard.writeText(manualConfig)}>
          {t("复制高级配置")}
        </Button>
        <p className="muted">
          {t("无 Web 服务的 CI/headless 场景仍可使用：gxworks-agent-mcp --standalone --workspace <workspace> --project <project-id>。")}
        </p>
      </details>
    </div>
  );
}

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
  const [page, setPage] = useState<"models" | "integrations">("models");
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
  const [discoveredModels, setDiscoveredModels] = useState<string[]>([]);
  const [detected, setDetected] = useState<string[]>([]);
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
    setDiscoveredModels([]);
    setDetected([]);
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
  const discoverReady =
    !busy && !disabled && !!baseUrl.trim() && (!creating || !!secret.trim());

  if (page === "integrations") {
    return (
      <div>
        <nav className="settings-tabs" aria-label={t("接入设置")}>
          <Button variant="ghost" onClick={() => setPage("models")}>{t("模型 API")}</Button>
          <Button variant="primary">Integrations / MCP</Button>
        </nav>
        <McpIntegrations t={t} disabled={disabled} />
      </div>
    );
  }

  return (
    <div>
      <nav className="settings-tabs" aria-label={t("接入设置")}>
        <Button variant="primary">{t("模型 API")}</Button>
        <Button variant="ghost" onClick={() => setPage("integrations")}>Integrations / MCP</Button>
      </nav>
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
              setCapabilities({});
              setDefaults("{}");
              setOverrides("{}");
              setDiscoveredModels([]);
              setDetected([]);
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
        <div className="form-actions">
          <Button
            disabled={!discoverReady}
            onClick={() =>
              void run(async () => {
                const probeId = selected || value.active_profile_id || value.profiles?.[0]?.id || "";
                if (!probeId) throw new Error(t("没有可用于能力探测的基础配置。"));
                const draft = {
                  id: probeId,
                  name: name.trim() || "Custom API",
                  model: model.trim() || "__discover__",
                  base_url: baseUrl,
                  capabilities,
                  generation_defaults: parse(defaults),
                  request_overrides: parse(overrides),
                };
                const result = await api<{ status: string; message: string }>(
                  `/settings/profiles/${encodeURIComponent(probeId)}/test`,
                  "POST",
                  { profile: draft, ...(secret ? { api_key: secret } : {}) },
                );
                if (result.status !== "connected") throw new Error(result.message || t("连接失败"));
                const discovery = parseDiscovery(result.message);
                if (!discovery) {
                  setMessage(result.message || t("连接成功"));
                  return;
                }
                const models = discovery.models || [];
                setDiscoveredModels(models);
                if ((!model || !models.includes(model)) && discovery.recommended_model)
                  setModel(discovery.recommended_model);
                if (discovery.capabilities) setCapabilities(discovery.capabilities);
                setDetected(discovery.detected || []);
                setMessage(discovery.note || t("模型列表与能力检测完成"));
              })
            }
          >
            {t(busy ? "检测中…" : "自动获取模型 + 检测能力")}
          </Button>
        </div>
        <label>
          {t("模型")}
          {discoveredModels.length ? (
            <select value={model} onChange={(e) => setModel(e.target.value)}>
              {discoveredModels.map((item) => <option value={item} key={item}>{item}</option>)}
            </select>
          ) : (
            <input value={model} onChange={(e) => setModel(e.target.value)} placeholder={t("可先自动获取模型")} />
          )}
        </label>
        {detected.length > 0 && (
          <p className="muted">
            {t("已检测")}: {detected.map((key) => `${key}=${capabilities[key] ? "✓" : "×"}`).join(" · ")}
          </p>
        )}
        <details>
          <summary>{t("高级设置")}</summary>
          <p className="muted">
            {t("普通用户无需修改。仅在供应商文档明确要求时调整 capability、生成参数或请求覆盖参数。")}
          </p>
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
                if (result.status === "connected") {
                  const discovery = parseDiscovery(result.message);
                  setMessage(discovery?.note || t("连接成功"));
                } else setError(result.message || t("连接失败"));
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
    </div>
  );
}
