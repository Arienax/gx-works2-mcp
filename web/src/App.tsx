import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties, FormEvent, ReactNode } from "react";
import {
  Activity,
  ArrowDownToLine,
  ArrowLeft,
  Bot,
  Check,
  ChevronDown,
  ChevronRight,
  Circle,
  CircuitBoard,
  Code2,
  FileCheck2,
  FileCode2,
  FolderOpen,
  GitBranch,
  History,
  Layers,
  LoaderCircle,
  Maximize2,
  Minus,
  Moon,
  PanelLeftClose,
  Paperclip,
  Play,
  Plus,
  RefreshCw,
  Send,
  Settings2,
  ShieldCheck,
  Square,
  Sun,
  Workflow,
  X,
} from "lucide-react";
import { api, activeJob, artifactUrl, key, setSession } from "./api/client";
import type {
  Artifact,
  Job,
  JobEvent,
  JobKind,
  Json,
  ModelSettings,
  Project,
  Proposal,
  Session,
  Spec,
} from "./api/client";
import { Badge, Button, Modal } from "./components/ui";
import { statusText, statusTone, translate } from "./i18n";
import type { Locale } from "./i18n";
import { SpecEditor } from "./features/SpecEditor";
import { Settings } from "./features/Settings";

let bootstrapToken =
  new URLSearchParams(location.hash.slice(1)).get("token") || "";
if (bootstrapToken)
  history.replaceState(null, "", location.pathname + location.search);
const stringify = (value: unknown) => JSON.stringify(value, null, 2);

export default function App() {
  const [locale, setLocale] = useState<Locale>(
    () => (localStorage.getItem("gx.locale") as Locale) || "zh-CN",
  );
  const t = useCallback((s: string) => translate(locale, s), [locale]);
  const [session, updateSession] = useState<Session | null>(null),
    [connecting, setConnecting] = useState(true);
  const [token, setToken] = useState(""),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [projects, setProjects] = useState<Project[]>([]),
    [project, setProject] = useState<Project | null>(null);
  const [pid, setPid] = useState(
      new URLSearchParams(location.search).get("project") || "",
    ),
    [vid, setVid] = useState("");
  const [refresh, setRefresh] = useState(0),
    [loading, setLoading] = useState(false);
  const [tab, setTab] = useState("ladder"),
    [panel, setPanel] = useState("agent"),
    [leftOpen, setLeftOpen] = useState(window.innerWidth > 900);
  const [settings, setSettings] = useState<ModelSettings | null>(null),
    [environment, setEnvironment] = useState<Record<string, Json>>({});
  const [jobs, setJobs] = useState<Job[]>([]),
    [jobId, setJobId] = useState(""),
    [events, setEvents] = useState<JobEvent[]>([]);
  const [proposals, setProposals] = useState<Proposal[]>([]),
    [selectedProposal, setSelectedProposal] = useState<Proposal | null>(null);
  const [preview, setPreview] = useState<Record<string, Json> | null>(null),
    [spec, setSpec] = useState<Spec | null>(null);
  const [analysisOutput, setAnalysisOutput] = useState<Record<
    string,
    Json
  > | null>(null);
  const [program, setProgram] = useState<Record<string, Json> | null>(null),
    [diagnostics, setDiagnostics] = useState<Json>(null),
    [report, setReport] = useState<Json>(null);
  const [network, setNetwork] = useState<Record<string, Json> | null>(null),
    [st, setSt] = useState("");
  const [zoom, setZoom] = useState(1),
    [rightWidth, setRightWidth] = useState(370);
  const [theme, setTheme] = useState<"light" | "dark">(() =>
    localStorage.getItem("gx.theme") === "light" ? "light" : "dark",
  );
  const [text, setText] = useState(""),
    [intent, setIntent] = useState<"analysis" | "generation" | "agent">(
      "analysis",
    );
  const [attachments, setAttachments] = useState<
      { attachment_id: string; filename: string }[]
    >([]),
    [busy, setBusy] = useState(false);
  const [modal, setModal] = useState(""),
    [newName, setNewName] = useState(""),
    [newMode, setNewMode] = useState<"ladder" | "st">("ladder");
  const [steps, setSteps] = useState([
    { name: "", action: "", transition: "" },
  ]);
  const uploadRef = useRef<HTMLInputElement>(null);
  const specBinding = useRef("");
  const activeProjectRef = useRef(pid);
  const projectEpoch = useRef(0);
  useEffect(() => {
    projectEpoch.current += 1;
    activeProjectRef.current = pid;
    setAttachments([]);
    setVid("");
    setProgram(null);
    setSt("");
    setJobs([]);
    setJobId("");
    setEvents([]);
    setAnalysisOutput(null);
    setProposals([]);
    setSpec(null);
    setNetwork(null);
  }, [pid]);
  const version = project?.versions?.find((v) => v.id === vid);
  const currentJob = jobs.find((j) => j.id === jobId);
  const pendingCount = proposals.filter((p) => p.status === "pending").length;
  const canWrite = !!session && !session.read_only && !busy && !loading;
  const operations = version?.capabilities?.operations || {};
  const refreshAll = () => setRefresh((n) => n + 1);
  const guarded = async (action: () => Promise<void>) => {
    if (busy) return;
    const epoch = projectEpoch.current;
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (e) {
      if (epoch === projectEpoch.current)
        setError(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    localStorage.setItem("gx.locale", locale);
    document.documentElement.lang = locale;
  }, [locale]);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("gx.theme", theme);
  }, [theme]);
  useEffect(() => {
    let stopped = false;
    const credential = bootstrapToken;
    bootstrapToken = "";
    (async () => {
      try {
        const value = credential
          ? await api<Session>("/session", "POST", { token: credential })
          : await api<Session>("/session");
        if (!stopped) {
          setSession(value);
          updateSession(value);
        }
      } catch {
        /* login form handles absent/expired session */
      } finally {
        if (!stopped) setConnecting(false);
      }
    })();
    return () => {
      stopped = true;
    };
  }, []);
  useEffect(() => {
    if (!session) return;
    let stopped = false;
    api<{ projects: Project[] }>("/projects")
      .then((result) => {
        if (stopped) return;
        setProjects(result.projects);
        setPid((selected) =>
          selected && result.projects.some((p) => p.id === selected)
            ? selected
            : result.projects[0]?.id || "",
        );
      })
      .catch((e) => setError(e.message));
    api<ModelSettings>("/settings")
      .then((v) => {
        if (!stopped) setSettings(v);
      })
      .catch((e) => setError(e.message));
    api<Record<string, Json>>("/environment")
      .then((v) => {
        if (!stopped) setEnvironment(v);
      })
      .catch((e) => setError(e.message));
    return () => {
      stopped = true;
    };
  }, [session, refresh]);
  useEffect(() => {
    if (!pid || !session) {
      setProject(null);
      return;
    }
    let stopped = false;
    setLoading(true);
    setSelectedProposal(null);
    setPreview(null);
    history.replaceState(null, "", `?project=${encodeURIComponent(pid)}`);
    api<Project>(`/projects/${pid}`)
      .then((value) => {
        if (stopped) return;
        setProject(value);
        const binding = value.id + ":" + (value.confirmed_spec_hash || "");
        if (specBinding.current !== binding) {
          specBinding.current = binding;
          setSpec((value.confirmed_spec as Spec) || null);
        }
        setVid((old) =>
          value.versions?.some((v) => v.id === old)
            ? old
            : value.active_version_id || value.versions?.[0]?.id || "",
        );
      })
      .catch((e) => setError(e.message))
      .finally(() => {
        if (!stopped) setLoading(false);
      });
    return () => {
      stopped = true;
    };
  }, [pid, session, refresh]);
  useEffect(() => {
    if (!pid || !vid || !session) {
      setProgram(null);
      setSt("");
      return;
    }
    let stopped = false;
    setNetwork(null);
    setDiagnostics(null);
    setReport(null);
    const path = `/projects/${pid}/versions/${vid}`;
    api<Record<string, Json>>(path + "/program")
      .then((v) => {
        if (!stopped) setProgram(v);
      })
      .catch((e) => setError(e.message));
    api<Json>(path + "/diagnostics")
      .then((v) => {
        if (!stopped) setDiagnostics(v);
      })
      .catch(() => {
        if (!stopped) setDiagnostics(null);
      });
    const artifact = version?.artifacts?.find(
      (a) => ["st_from_ir", "st"].includes(a.id) && a.available,
    );
    if (artifact)
      fetch(artifactUrl(pid, vid, artifact.id))
        .then(async (r) => {
          if (!r.ok) throw new Error(t("此版本没有该产物"));
          return r.text();
        })
        .then((v) => {
          if (!stopped) setSt(v);
        })
        .catch((e) => setError(e.message));
    else setSt("");
    return () => {
      stopped = true;
    };
  }, [pid, vid, version, session, t]);
  useEffect(() => {
    if (!session) return;
    let stopped = false;
    async function poll() {
      try {
        const [j, p] = await Promise.all([
          api<{ jobs: Job[] }>(`/jobs${pid ? `?project_id=${pid}` : ""}`),
          api<{ proposals: Proposal[] }>(
            `/proposals${pid ? `?project_id=${pid}` : ""}`,
          ),
        ]);
        if (!stopped) {
          setJobs(j.jobs);
          setProposals(p.proposals);
          setJobId((old) =>
            j.jobs.some((item) => item.id === old) ? old : j.jobs[0]?.id || "",
          );
        }
      } catch (e) {
        if (!stopped) setError((e as Error).message);
      }
    }
    void poll();
    const interval = setInterval(poll, 2500);
    return () => {
      stopped = true;
      clearInterval(interval);
    };
  }, [session, pid, refresh]);
  useEffect(() => {
    setAnalysisOutput(null);
    if (!jobId || !session) {
      setEvents([]);
      return;
    }
    setEvents([]);
    let sequence = 0;
    let stopped = false;
    const stream = new EventSource(`/api/jobs/${jobId}/events`);
    stream.onmessage = (event) => {
      const value = JSON.parse(event.data) as JobEvent;
      if (value.sequence <= sequence) return;
      sequence = value.sequence;
      setEvents((old) => [...old, value]);
      if (
        ["completed", "failed", "cancelled", "interrupted"].includes(
          value.event_type,
        )
      ) {
        stream.close();
        if (value.event_type === "completed")
          api<Record<string, Json>>(`/jobs/${jobId}/output`)
            .then((output) => {
              if (stopped || activeProjectRef.current !== value.project_id)
                return;
              if (output.spec_draft) {
                setAnalysisOutput(output);
              }
            })
            .catch(() => {});
        setRefresh((n) => n + 1);
      }
    };
    return () => {
      stopped = true;
      stream.close();
    };
  }, [jobId, session]);
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(""), 4000);
    return () => clearTimeout(timer);
  }, [notice]);

  async function submitJob(
    kind: JobKind = intent,
    extra: Record<string, unknown> = {},
  ) {
    if (!project) return;
    const epoch = projectEpoch.current;
    const job = await api<Job>("/jobs", "POST", {
      kind,
      project_id: pid,
      version_id: vid || null,
      request_id: key(),
      text,
      response_language: locale,
      attachment_ids: attachments.map((a) => a.attachment_id),
      ...extra,
    });
    if (activeProjectRef.current !== pid || epoch !== projectEpoch.current)
      return;
    setJobId(job.id);
    setJobs((old) => [job, ...old]);
    setPanel("agent");
    setAttachments([]);
    refreshAll();
  }
  async function saveSpec(value: Spec) {
    const epoch = projectEpoch.current;
    const result = await api<{ valid: boolean; issues?: unknown }>(
      `/projects/${pid}/spec`,
      "PUT",
      { spec: value, expected_hash: project?.confirmed_spec_hash ?? null },
    );
    if (activeProjectRef.current !== pid || epoch !== projectEpoch.current)
      return;
    if (!result.valid) {
      setReport(result.issues as Json);
      setModal("report");
      return;
    }
    setNotice(t("规格已确认"));
    setIntent("generation");
    refreshAll();
  }
  async function showProposal(value: Proposal, previewTheme = theme) {
    const epoch = projectEpoch.current;
    setSelectedProposal(null);
    setPreview(null);
    const loaded = await api<Record<string, Json>>(
      `/proposals/${value.id}/preview?theme=${previewTheme}`,
    );
    if (
      activeProjectRef.current !== value.project_id ||
      epoch !== projectEpoch.current
    )
      return;
    setPreview(loaded);
    setSelectedProposal(value);
    setPanel("proposals");
    setTab(loaded.target_mode === "st" ? "st" : "ladder");
  }
  async function decide(value: Proposal, decision: "accept" | "reject") {
    const epoch = projectEpoch.current;
    const result = await api<{ proposal?: Proposal; job?: Job }>(
      `/proposals/${value.id}/decision`,
      "POST",
      { decision },
    );
    if (
      activeProjectRef.current !== value.project_id ||
      epoch !== projectEpoch.current
    )
      return;
    if (result.job) {
      setJobId(result.job.id);
      setJobs((old) => [result.job!, ...old]);
    }
    if (result.proposal?.result?.version_id)
      setVid(String(result.proposal.result.version_id));
    setSelectedProposal(null);
    setPreview(null);
    setNotice(t("操作完成"));
    refreshAll();
  }
  async function proposeExecution(
    action: string,
    planId?: string,
    versionId = vid,
  ) {
    const epoch = projectEpoch.current;
    const value = await api<Proposal>("/proposals", "POST", {
      action,
      project_id: pid,
      version_id: versionId,
      plan_id: planId || null,
      request_id: key(),
    });
    if (activeProjectRef.current !== pid || epoch !== projectEpoch.current)
      return;
    setProposals((old) => [value, ...old]);
    await showProposal(value);
  }
  async function upload(files: FileList | null) {
    if (!files) return;
    for (const file of Array.from(files)) {
      const encoded = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(",")[1]);
        reader.onerror = reject;
        reader.readAsDataURL(file);
      });
      const uploadProject = pid;
      const added = await api<{ attachment_id: string; filename: string }>(
        `/projects/${pid}/attachments`,
        "POST",
        { filename: file.name, data_base64: encoded },
      );
      if (activeProjectRef.current === uploadProject)
        setAttachments((old) => [...old, added]);
    }
  }
  function resizePanel(event: React.PointerEvent) {
    const start = event.clientX,
      width = rightWidth;
    event.currentTarget.setPointerCapture(event.pointerId);
    const move = (e: PointerEvent) =>
      setRightWidth(Math.max(300, Math.min(650, width + start - e.clientX)));
    const end = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", end);
  }
  function toggleTheme() {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    if (selectedProposal)
      void guarded(() => showProposal(selectedProposal, next));
  }
  const model = settings?.profiles?.find(
    (p) => p.id === settings.active_profile_id,
  );
  const visibleProgram = preview
    ? (preview.program as Record<string, Json> | undefined)
    : program;
  const networks = Array.isArray(visibleProgram?.networks)
    ? (visibleProgram.networks as Record<string, Json>[])
    : [];
  const svg = preview?.svg
    ? `data:image/svg+xml;charset=utf-8,${encodeURIComponent(String(preview.svg))}`
    : !preview && version?.artifacts?.find((a) => a.id === "svg" && a.available)
      ? artifactUrl(pid, vid, "svg") + `?theme=${theme}`
      : "";
  const status = (value?: string | null) => (
    <Badge tone={statusTone(value || "unknown")}>
      {statusText(locale, value || "unknown")}
    </Badge>
  );
  const latestMessage = events
    .filter((e) => e.event_type === "progress")
    .at(-1)?.payload;
  const eventText = (kind: string) =>
    events
      .filter((e) => e.event_type === kind)
      .map((e) => e.payload?.text || e.payload?.message || "")
      .join("");

  if (!session)
    return (
      <div className="login-shell">
        <div className="login-card">
          <CircuitBoard size={38} />
          <h1>
            GXWorks <span>Agent</span>
          </h1>
          <p className="eyebrow">{t("工程工作台")}</p>
          {connecting ? (
            <p>
              <LoaderCircle className="spin" size={16} />{" "}
              {t("正在连接本地服务")}
            </p>
          ) : (
            <form
              onSubmit={(e: FormEvent) => {
                e.preventDefault();
                void guarded(async () => {
                  const value = await api<Session>("/session", "POST", {
                    token,
                  });
                  setSession(value);
                  updateSession(value);
                  setToken("");
                });
              }}
            >
              <h2>{t("操作员登录")}</h2>
              <p className="muted">
                {t("输入本地服务启动时提供的操作员令牌。")}
              </p>
              <input
                type="password"
                autoComplete="off"
                required
                aria-label="Operator token"
                value={token}
                onChange={(e) => setToken(e.target.value)}
              />
              <Button variant="primary" disabled={busy}>
                {t("连接")}
              </Button>
            </form>
          )}
          {error && (
            <p role="alert" className="error-text">
              {error}
            </p>
          )}
        </div>
      </div>
    );

  return (
    <div
      className={`workbench ${leftOpen ? "" : "sidebar-hidden"}`}
      style={{ "--inspector-width": `${rightWidth}px` } as CSSProperties}
    >
      <header className="app-header">
        <div className="brand">
          <CircuitBoard size={24} />
          <strong>
            GXWorks <span>Agent</span>
          </strong>
          <span className="edition">WORKBENCH</span>
        </div>
        <div className="header-center">
          <span className="connection-dot" />
          {t("本地服务")}
          <span className="separator">/</span>
          {t("工程工作台")}
        </div>
        <div className="header-actions">
          <button
            className="icon-button"
            disabled={busy}
            aria-label={t(theme === "dark" ? "切换浅色主题" : "切换深色主题")}
            title={t(theme === "dark" ? "切换浅色主题" : "切换深色主题")}
            onClick={toggleTheme}
          >
            {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
          </button>
          {session.read_only && <Badge tone="warn">{t("只读")}</Badge>}
          <select
            aria-label={t("响应语言")}
            className="language-select"
            value={locale}
            onChange={(e) => setLocale(e.target.value as Locale)}
          >
            <option value="zh-CN">简体中文</option>
            <option value="en">English</option>
            <option value="ja">日本語</option>
          </select>
          <button
            className="icon-button"
            aria-label={t("模型设置")}
            title={t("模型设置")}
            onClick={() => setModal("settings")}
          >
            <Settings2 size={18} />
          </button>
        </div>
      </header>
      <aside className="project-sidebar">
        <div className="sidebar-heading">
          <span>{t("工程")}</span>
          <Button
            variant="ghost"
            aria-label={t("新建工程")}
            disabled={!canWrite}
            onClick={() => setModal("new")}
          >
            <Plus size={16} />
          </Button>
        </div>
        <div className="project-list">
          {projects.map((p) => (
            <button
              key={p.id}
              disabled={busy}
              className={`project-item ${pid === p.id ? "selected" : ""}`}
              onClick={() => {
                if (p.id === pid) return;
                setPid(p.id);
              }}
            >
              <FolderOpen size={17} />
              <span>
                {p.name}
                <small>
                  {p.plc_model} · {p.target_mode.toUpperCase()}
                </small>
              </span>
              {pid === p.id && <ChevronRight size={14} />}
            </button>
          ))}
        </div>
        <div className="sidebar-heading versions-title">
          <span>{t("版本历史")}</span>
          <History size={15} />
        </div>
        <div className="version-list">
          {project?.versions
            ?.slice()
            .reverse()
            .map((v) => (
              <button
                className={`version-item ${v.id === vid ? "selected" : ""}`}
                key={v.id}
                disabled={busy}
                onClick={() => {
                  setVid(v.id);
                  setPreview(null);
                  setSelectedProposal(null);
                }}
              >
                <GitBranch size={15} />
                <span>
                  <strong className="mono">{v.id}</strong>
                  <small>
                    {new Date(v.created_at || "").toLocaleString(locale, {
                      month: "2-digit",
                      day: "2-digit",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </small>
                </span>
                {v.id === project.active_version_id && (
                  <span className="active-version" title={t("当前版本")} />
                )}
              </button>
            ))}
          {!project?.versions?.length && (
            <p className="sidebar-empty">{t("暂无版本")}</p>
          )}
        </div>
        <div className="sidebar-bottom">
          <button onClick={() => setModal("environment")}>
            <Activity size={16} />
            <span>GX Works2</span>
            <span className="muted">
              {String(environment.status || t("未运行"))}
            </span>
          </button>
          <button onClick={() => setModal("settings")}>
            <Bot size={16} />
            <span>{model?.name || t("模型设置")}</span>
            <span
              className={`small-dot ${model?.configured ? "good" : "warn"}`}
            />
          </button>
        </div>
      </aside>
      <main className="engineering-area">
        <div className="project-bar">
          <button
            className="icon-button"
            title={t("工程")}
            onClick={() => setLeftOpen((v) => !v)}
          >
            <PanelLeftClose size={17} />
          </button>
          <div className="project-title">
            <h1>{project?.name || t("选择工程")}</h1>
            <span>
              {project?.plc_model || "MITSUBISHI FX"}
              {vid && (
                <>
                  {" "}
                  <span className="separator">/</span>{" "}
                  <span className="mono">{vid}</span>
                </>
              )}
            </span>
          </div>
          {version && status(version.validation?.status || version.target_mode)}
          <div className="project-actions">
            <Button variant="ghost" aria-label={t("刷新")} onClick={refreshAll}>
              <RefreshCw size={15} />
            </Button>
            {version && vid !== project?.active_version_id && (
              <Button
                disabled={!canWrite}
                onClick={() =>
                  void guarded(async () => {
                    await api(`/projects/${pid}/active-version`, "POST", {
                      version_id: vid,
                      expected_active_version_id: project?.active_version_id,
                    });
                    refreshAll();
                  })
                }
              >
                {t("设为当前版本")}
              </Button>
            )}
            <Button
              disabled={!canWrite || !pid}
              title={t("从 GX 读取")}
              onClick={() => void guarded(() => submitJob("gx_read"))}
            >
              <ArrowLeft size={15} />
              {t("从 GX 读取")}
            </Button>
            <Button
              disabled={!canWrite || !pid}
              title={t("检查同步")}
              onClick={() => void guarded(() => submitJob("gx_inspect"))}
            >
              <GitBranch size={15} />
            </Button>
            <Button
              disabled={!canWrite || !operations.gx_import}
              onClick={() => void guarded(() => proposeExecution("gx_import"))}
            >
              <ArrowDownToLine size={15} />
              {t("导入 GX")}
            </Button>
          </div>
        </div>
        <nav className="editor-tabs">
          {(
            [
              ["ladder", t("梯形图"), <Workflow size={15} />],
              ["st", "ST", <Code2 size={15} />],
              ["diagnostics", t("诊断"), <ShieldCheck size={15} />],
              ["reports", t("检查报告"), <FileCheck2 size={15} />],
              ["simulation", t("仿真记录"), <Activity size={15} />],
            ] as [string, string, ReactNode][]
          ).map(([id, title, icon]) => (
            <button
              key={id}
              className={tab === id ? "active" : ""}
              onClick={() => setTab(id)}
            >
              {icon}
              {title}
            </button>
          ))}
        </nav>
        {selectedProposal && (
          <div className="preview-banner">
            <GitBranch size={16} />
            <strong>{t("候选预览")}</strong>
            <span>
              {t("基础版本")}{" "}
              {selectedProposal.base_version_id || t("首次生成")}
            </span>
            {status(selectedProposal.status)}
            <Button
              variant="ghost"
              onClick={() => {
                setPreview(null);
                setSelectedProposal(null);
              }}
            >
              <ArrowLeft size={14} />
              {t("返回版本")}
            </Button>
          </div>
        )}
        <div className="editor-content">
          {loading ? (
            <div className="empty-state">
              <LoaderCircle size={28} className="spin" />
              <p>{t("正在读取工程")}</p>
            </div>
          ) : !project ? (
            <div className="empty-state">
              <FolderOpen size={42} />
              <h2>{t("打开本地工程")}</h2>
              <p>{t("选择已有工程，或创建一个新工程开始。")}</p>
              <Button
                variant="primary"
                disabled={!canWrite}
                onClick={() => setModal("new")}
              >
                <Plus size={16} />
                {t("新建工程")}
              </Button>
            </div>
          ) : !version && !preview ? (
            <div className="empty-state">
              <Workflow size={44} />
              <h2>{t("工程中还没有程序")}</h2>
              <p>{t("描述控制需求，确认规格后生成第一个候选程序。")}</p>
              <Badge>
                {project.plc_model} · {project.target_mode.toUpperCase()}
              </Badge>
            </div>
          ) : tab === "ladder" ? (
            <div className="canvas-shell">
              <div className="canvas-toolbar">
                <span>
                  <Layers size={14} />
                  MAIN{" "}
                  <span className="canvas-caption">
                    {networks.length ? `${networks.length} ${t("网络")}` : ""}
                  </span>
                </span>
                <div>
                  <button
                    aria-label={t("缩小")}
                    onClick={() => setZoom((v) => Math.max(0.25, v - 0.1))}
                  >
                    <Minus size={15} />
                  </button>
                  <button className="mono" onClick={() => setZoom(1)}>
                    {Math.round(zoom * 100)}%
                  </button>
                  <button
                    aria-label={t("放大")}
                    onClick={() => setZoom((v) => Math.min(3, v + 0.1))}
                  >
                    <Plus size={15} />
                  </button>
                  <button aria-label={t("适应画布")} onClick={() => setZoom(1)}>
                    <Maximize2 size={15} />
                  </button>
                  <button
                    aria-label={t(
                      theme === "dark" ? "切换浅色主题" : "切换深色主题",
                    )}
                    disabled={busy}
                    onClick={toggleTheme}
                  >
                    {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
                  </button>
                </div>
              </div>
              <div className="canvas-scroll">
                {svg ? (
                  <img
                    className="ladder-artifact"
                    alt={t("梯形图")}
                    src={svg}
                    style={{ width: `${zoom * 100}%`, maxWidth: "none" }}
                  />
                ) : (
                  <div className="empty-state">
                    <FileCode2 size={32} />
                    <p>{t("此版本没有该产物")}</p>
                    {preview?.st && (
                      <Button onClick={() => setTab("st")}>ST</Button>
                    )}
                  </div>
                )}
              </div>
              {networks.length > 0 && (
                <div className="network-strip">
                  {networks.map((n, i) => (
                    <button
                      key={String(n.id || i)}
                      className={n === network ? "active" : ""}
                      onClick={() => {
                        setNetwork(n);
                        setPanel("inspector");
                      }}
                    >
                      <Circle size={8} />
                      {String(n.id || `N${i + 1}`)}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ) : tab === "st" ? (
            <div className="code-view">
              <header>
                <FileCode2 size={15} />
                {preview
                  ? "candidate.st"
                  : version?.artifacts?.find((a) => a.id.includes("st"))
                      ?.filename || "ST"}
                <span className="spacer" />
                {!preview &&
                  version?.artifacts
                    ?.filter(
                      (a) => ["st", "st_from_ir"].includes(a.id) && a.available,
                    )
                    .map((a) => (
                      <a key={a.id} href={artifactUrl(pid, vid, a.id, true)}>
                        <ArrowDownToLine size={14} />
                        {t("下载")}
                      </a>
                    ))}
              </header>
              <pre>
                {String((preview ? preview.st : st) || t("此版本没有该产物"))}
              </pre>
            </div>
          ) : tab === "diagnostics" ? (
            <div className="document-view">
              <div className="content-heading">
                <h2>{t("诊断")}</h2>
                <Button
                  disabled={!canWrite || !operations.diagnose}
                  onClick={() =>
                    void guarded(() => submitJob("review", { deep: false }))
                  }
                >
                  <ShieldCheck size={15} />
                  {t("本地检查")}
                </Button>
              </div>
              <DataView value={diagnostics} />
            </div>
          ) : tab === "reports" ? (
            <div className="document-view">
              <div className="content-heading">
                <h2>{t("检查报告")}</h2>
                <Button
                  disabled={!canWrite || !operations.diagnose}
                  onClick={() => void guarded(() => submitJob("review"))}
                >
                  <FileCheck2 size={15} />
                  {t("本地检查")} + AI
                </Button>
              </div>
              {project.reports?.length ? (
                project.reports.map((r) => (
                  <button
                    className="report-item"
                    key={r.report_id}
                    onClick={() =>
                      void guarded(async () => {
                        setReport(
                          await api(`/projects/${pid}/reports/${r.report_id}`),
                        );
                        setModal("report");
                      })
                    }
                  >
                    <FileCheck2 size={20} />
                    <span>
                      {r.summary || r.report_id}
                      <small className="mono">
                        {r.base_version_id} · {r.report_id}
                      </small>
                    </span>
                    {status(r.status)}
                    <ChevronRight size={16} />
                  </button>
                ))
              ) : (
                <div className="panel-empty">{t("没有检查报告")}</div>
              )}
            </div>
          ) : (
            <div className="document-view">
              <div className="content-heading">
                <h2>{t("仿真记录")}</h2>
                <Button
                  disabled={!canWrite || !operations.simulation}
                  onClick={() => void guarded(() => submitJob("test_plan"))}
                >
                  <Plus size={15} />
                  {t("生成测试方案")}
                </Button>
              </div>
              <p className="muted">{t("实际仿真结果以保存的证据为准。")}</p>
              {version?.simulator_test_plans?.map((p, i) => (
                <div className="report-item" key={i}>
                  <FileCheck2 size={18} />
                  <span>{String(p.name || p.suite_name || p.plan_id)}</span>
                  <Button
                    disabled={!canWrite}
                    onClick={() =>
                      void guarded(() =>
                        proposeExecution("simulation", String(p.plan_id)),
                      )
                    }
                  >
                    <Play size={14} />
                    {t("运行指定方案")}
                  </Button>
                </div>
              ))}
              {version?.simulator_runs?.length ? (
                version.simulator_runs.map((r, i) => (
                  <div className="report-item" key={i}>
                    <Activity size={20} />
                    <button
                      className="text-button"
                      onClick={() =>
                        void guarded(async () => {
                          setReport(
                            await api(
                              `/projects/${pid}/versions/${vid}/runs/${r.run_id}`,
                            ),
                          );
                          setModal("report");
                        })
                      }
                    >
                      {String(r.suite_name || r.run_id)}
                    </button>
                    <span className="spacer" />
                    {status(String(r.status))}
                    <Button
                      disabled={!canWrite}
                      onClick={() =>
                        void guarded(() =>
                          submitJob("debug_plan", { run_id: r.run_id }),
                        )
                      }
                    >
                      {t("准备调试方案")}
                    </Button>
                  </div>
                ))
              ) : (
                <div className="panel-empty">{t("没有仿真记录")}</div>
              )}
            </div>
          )}
        </div>
        {version && !preview && (
          <footer className="artifact-footer">
            <span>
              <FileCode2 size={13} />
              {t("产物来自后端工程核心")}
            </span>
            <div>
              {(version.artifacts || [])
                .filter(
                  (a) =>
                    a.available && !["svg", "st", "st_from_ir"].includes(a.id),
                )
                .map((a: Artifact) => (
                  <a href={artifactUrl(pid, vid, a.id, true)} key={a.id}>
                    {a.id.replace("_", " ")} <ArrowDownToLine size={12} />
                  </a>
                ))}
            </div>
          </footer>
        )}
      </main>
      <div
        role="separator"
        aria-label={t("检查器")}
        aria-orientation="vertical"
        tabIndex={0}
        className="panel-resizer"
        onPointerDown={resizePanel}
        onKeyDown={(e) => {
          if (e.key === "ArrowLeft")
            setRightWidth((v) => Math.min(650, v + 20));
          if (e.key === "ArrowRight")
            setRightWidth((v) => Math.max(300, v - 20));
        }}
      />
      <aside className="agent-sidebar">
        <nav className="panel-tabs">
          {[
            ["agent", "Agent"],
            ["spec", t("规格")],
            [
              "proposals",
              `${t("待审批")}${pendingCount ? ` ${pendingCount}` : ""}`,
            ],
            ["inspector", t("检查器")],
          ].map(([id, label]) => (
            <button
              key={id}
              className={panel === id ? "active" : ""}
              onClick={() => setPanel(id)}
            >
              {label}
            </button>
          ))}
        </nav>
        {panel === "agent" ? (
          <>
            <div className="agent-heading">
              <Bot size={20} />
              <div>
                <strong>Engineering Agent</strong>
                <small>{model?.model || t("未配置密钥")}</small>
              </div>
              <Badge>{locale}</Badge>
            </div>
            <div className="conversation">
              <div className="agent-intro">
                <span className="agent-mark">
                  <CircuitBoard size={22} />
                </span>
                <h2>{t("工程工作台")}</h2>
                <p>{t("描述控制需求，确认规格后生成第一个候选程序。")}</p>
                <div className="context-chips">
                  <Badge>{project?.plc_model || "FX3U"}</Badge>
                  {vid && <Badge>{vid}</Badge>}
                  {project?.confirmed_spec && (
                    <Badge tone="good">
                      <Check size={12} />
                      {t("规格已确认")}
                    </Badge>
                  )}
                </div>
              </div>
              {currentJob && (
                <div className="job-conversation">
                  <div className="job-line">
                    <span>{currentJob.kind}</span>
                    {status(currentJob.status)}
                  </div>
                  {events.some((e) =>
                    ["reasoning", "progress"].includes(e.event_type),
                  ) && (
                    <details className="reasoning">
                      <summary>
                        <Workflow size={14} />
                        {t("思考与工具记录")}
                        <ChevronDown size={14} />
                      </summary>
                      {events
                        .filter((e) => e.event_type === "progress")
                        .map((e) => (
                          <p key={e.sequence}>
                            <Check size={11} />
                            {String(
                              e.payload?.message ||
                                e.payload?.text ||
                                e.payload?.stage ||
                                "",
                            )}
                          </p>
                        ))}
                      {eventText("reasoning") && (
                        <pre>{eventText("reasoning")}</pre>
                      )}
                    </details>
                  )}
                  {eventText("content") && (
                    <AcceptedMessage
                      kind={currentJob.kind}
                      text={eventText("content")}
                      t={t}
                    />
                  )}
                  {currentJob.error_code && (
                    <p className="error-text">{currentJob.error_code}</p>
                  )}
                  {!!analysisOutput?.spec_draft && (
                    <div>
                      <Button
                        disabled={
                          !canWrite ||
                          (analysisOutput.spec_base_hash ?? null) !==
                            (project?.confirmed_spec_hash ?? null) ||
                          (analysisOutput.base_version_id ?? null) !==
                            (vid || null)
                        }
                        onClick={() => {
                          setSpec(analysisOutput.spec_draft as Spec);
                          setPanel("spec");
                        }}
                      >
                        {t("查看规格草稿")}
                      </Button>
                      {(analysisOutput.spec_base_hash ?? null) !==
                        (project?.confirmed_spec_hash ?? null) && (
                        <p className="muted">
                          {t("规格已变化，请重新分析后再应用草稿。")}
                        </p>
                      )}
                    </div>
                  )}
                  {!!currentJob.result?.plan_id && (
                    <Button
                      disabled={!canWrite}
                      onClick={() =>
                        void guarded(() =>
                          proposeExecution(
                            currentJob.kind === "debug_plan"
                              ? "debug"
                              : "simulation",
                            String(currentJob.result?.plan_id),
                            currentJob.version_id || vid,
                          ),
                        )
                      }
                    >
                      {t("运行指定方案")}
                    </Button>
                  )}
                </div>
              )}
              <p className="acceptance-note">
                <ShieldCheck size={13} />
                {t("模型内容通过验收后显示。")}
              </p>
            </div>
            <div className="composer">
              <div className="composer-mode">
                <select
                  aria-label={t("输入方式")}
                  value={intent}
                  onChange={(e) => setIntent(e.target.value as typeof intent)}
                >
                  <option value="analysis">{t("分析需求")}</option>
                  <option value="generation">{t("生成候选")}</option>
                  <option value="agent">{t("询问 Agent")}</option>
                </select>
                <button
                  className="text-button"
                  disabled={!canWrite}
                  onClick={() => setModal("sfc")}
                >
                  SFC <Workflow size={13} />
                </button>
              </div>
              <textarea
                aria-label={t("描述你的控制需求…")}
                placeholder={t("描述你的控制需求…")}
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (
                    (e.ctrlKey || e.metaKey) &&
                    e.key === "Enter" &&
                    text.trim() &&
                    canWrite
                  )
                    void guarded(() => submitJob());
                }}
              />
              {attachments.length > 0 && (
                <div className="attachment-chips">
                  {attachments.map((a) => (
                    <button
                      key={a.attachment_id}
                      onClick={() =>
                        setAttachments((items) =>
                          items.filter(
                            (v) => v.attachment_id !== a.attachment_id,
                          ),
                        )
                      }
                    >
                      {a.filename}
                      <X size={12} />
                    </button>
                  ))}
                </div>
              )}
              <div className="composer-actions">
                <input
                  ref={uploadRef}
                  type="file"
                  hidden
                  multiple
                  accept="image/png,image/jpeg,image/gif,image/webp"
                  onChange={(e) => void guarded(() => upload(e.target.files))}
                />
                <Button
                  variant="ghost"
                  aria-label={t("添加图片")}
                  disabled={!canWrite || !pid}
                  onClick={() => uploadRef.current?.click()}
                >
                  <Paperclip size={16} />
                </Button>
                <span className="muted">Ctrl ↵</span>
                <Button
                  variant="primary"
                  disabled={!canWrite || !pid || !text.trim()}
                  onClick={() => void guarded(() => submitJob())}
                >
                  <Send size={14} />
                  {t("发送")}
                </Button>
              </div>
            </div>
          </>
        ) : panel === "spec" ? (
          <SpecEditor
            value={spec}
            t={t}
            disabled={!canWrite || !pid}
            onSave={(s) => void guarded(() => saveSpec(s))}
          />
        ) : panel === "proposals" ? (
          <div className="proposal-list">
            {proposals.length ? (
              proposals.map((p) => (
                <section
                  className={`proposal-card ${selectedProposal?.id === p.id ? "selected" : ""}`}
                  key={p.id}
                >
                  <div className="job-line">
                    <GitBranch size={15} />
                    <strong>
                      {p.action === "accept_local"
                        ? t("接受为本地版本")
                        : p.action}
                    </strong>
                    {status(p.status)}
                  </div>
                  <p>{String(p.summary?.summary || "")}</p>
                  <div className="proposal-meta">
                    {t("基础版本")}{" "}
                    <span className="mono">
                      {p.base_version_id || t("首次生成")}
                    </span>
                  </div>
                  <Button onClick={() => void guarded(() => showProposal(p))}>
                    {t("预览与差异")}
                    <ChevronRight size={14} />
                  </Button>
                  {!!p.summary?.diff && (
                    <details>
                      <summary>{t("差异数据")}</summary>
                      <DataView value={p.summary.diff} />
                    </details>
                  )}
                  {selectedProposal?.id === p.id && !!preview?.diff && (
                    <DiffView value={preview.diff} t={t} />
                  )}
                  {selectedProposal?.id === p.id && !!preview?.action && (
                    <div className="candidate-diff">
                      <p>
                        {t("审批绑定版本")}{" "}
                        <strong>{String(preview.version_id || "")}</strong>
                      </p>
                      {!!preview.plan && (
                        <>
                          <h3>{t("指定执行方案")}</h3>
                          <DataView value={preview.plan} />
                        </>
                      )}
                    </div>
                  )}
                  {!!p.summary?.validation && (
                    <DataView value={p.summary.validation} />
                  )}
                  <div className="proposal-actions">
                    {p.status === "pending" && (
                      <>
                        <Button
                          variant="ghost"
                          disabled={!canWrite}
                          onClick={() =>
                            void guarded(() => decide(p, "reject"))
                          }
                        >
                          {t("拒绝")}
                        </Button>
                        <Button
                          variant="primary"
                          disabled={!canWrite || selectedProposal?.id !== p.id}
                          title={t("预览与差异")}
                          onClick={() =>
                            void guarded(() => decide(p, "accept"))
                          }
                        >
                          <Check size={14} />
                          {t(
                            p.action === "accept_local"
                              ? "接受为本地版本"
                              : "批准执行",
                          )}
                        </Button>
                      </>
                    )}
                  </div>
                  {p.result && (
                    <div className="execution-result">
                      {t("执行结果")}{" "}
                      {status(String(p.result.status || p.status))}
                      <DataView value={p.result} />
                    </div>
                  )}
                </section>
              ))
            ) : (
              <div className="panel-empty">
                <ShieldCheck size={28} />
                <p>{t("暂无待审批提案")}</p>
              </div>
            )}
            <p className="muted footnote">
              {t("本地版本不代表 GX 编译或仿真通过。")}
            </p>
          </div>
        ) : (
          <div className="inspector">
            <div className="section-label">{t("网络")}</div>
            {network ? (
              <>
                <h2 className="mono">{String(network.id)}</h2>
                <DataView value={network} />
              </>
            ) : (
              <p className="muted">{t("选择网络查看地址和引用。")}</p>
            )}
            {preview && !preview.program && <DataView value={preview} />}
          </div>
        )}
      </aside>
      <footer className="task-dock">
        <div>
          <Activity size={15} />
          <strong>{t("任务")}</strong>
          <select
            aria-label={t("任务记录")}
            value={jobId}
            onChange={(e) => setJobId(e.target.value)}
          >
            <option value="">{t("暂无任务")}</option>
            {jobs.map((j) => (
              <option key={j.id} value={j.id}>
                {j.kind} · {statusText(locale, j.status)} · {j.id.slice(-6)}
              </option>
            ))}
          </select>
          {currentJob && status(currentJob.status)}
          {currentJob && activeJob(currentJob) && (
            <Button
              variant="ghost"
              title={t("安全检查点取消")}
              onClick={() =>
                void guarded(async () => {
                  await api(`/jobs/${jobId}/cancel`, "POST");
                  refreshAll();
                })
              }
            >
              <Square size={11} />
              {t("取消请求")}
            </Button>
          )}
        </div>
        <span className="dock-progress">
          {String(
            latestMessage?.message ||
              latestMessage?.text ||
              t("后端任务会在关闭或刷新页面后继续。"),
          )}
        </span>
        <span className="local-indicator">
          <span className="connection-dot" />
          {t("已连接")}
        </span>
      </footer>
      {(error || notice) && (
        <div
          className={`toast ${error ? "toast-error" : ""}`}
          role={error ? "alert" : "status"}
        >
          <span>{error || notice}</span>
          <button
            className="icon-button"
            aria-label={t("关闭")}
            onClick={() => {
              setError("");
              setNotice("");
            }}
          >
            <X size={16} />
          </button>
        </div>
      )}
      <Modal
        open={modal === "new"}
        onOpenChange={(v) => !v && setModal("")}
        title={t("新建工程")}
      >
        <form
          className="form"
          onSubmit={(e) => {
            e.preventDefault();
            void guarded(async () => {
              const p = await api<Project>("/projects", "POST", {
                name: newName,
                target_mode: newMode,
                plc_model: "FX3U",
              });
              setPid(p.id);
              setVid("");
              setModal("");
              setNewName("");
              refreshAll();
            });
          }}
        >
          <label>
            {t("项目名称")}
            <input
              autoFocus
              required
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
            />
          </label>
          <label>
            {t("程序形式")}
            <select
              value={newMode}
              onChange={(e) => setNewMode(e.target.value as typeof newMode)}
            >
              <option value="ladder">{t("梯形图")} · FX3U</option>
              <option value="st">ST · FX3U</option>
            </select>
          </label>
          <Button variant="primary" disabled={busy}>
            <Plus size={15} />
            {t("创建")}
          </Button>
        </form>
      </Modal>
      <Modal
        open={modal === "settings"}
        onOpenChange={(v) => !v && setModal("")}
        title={t("模型设置")}
      >
        {settings && (
          <Settings
            value={settings}
            t={t}
            disabled={!session || !!session.read_only}
            onChange={setSettings}
          />
        )}
      </Modal>
      <Modal
        open={modal === "environment"}
        onOpenChange={(v) => !v && setModal("")}
        title={t("环境详情")}
      >
        <DataView value={environment} />
      </Modal>
      <Modal
        open={modal === "report"}
        onOpenChange={(v) => !v && setModal("")}
        title={t("检查报告详情")}
      >
        <DataView value={report} />
      </Modal>
      <Modal
        open={modal === "sfc"}
        onOpenChange={(v) => !v && setModal("")}
        title={t("SFC 需求输入")}
        description={t("此输入生成需求文本，不编译 GX SFC 工程。")}
      >
        <div className="sfc-steps">
          {steps.map((s, i) => (
            <div className="sfc-step" key={i}>
              <span className="step-number">{i + 1}</span>
              <div>
                {(["name", "action", "transition"] as const).map((field, n) => (
                  <input
                    key={field}
                    aria-label={t(["步骤名称", "动作", "转移条件"][n])}
                    placeholder={t(["步骤名称", "动作", "转移条件"][n])}
                    value={s[field]}
                    onChange={(e) =>
                      setSteps((old) =>
                        old.map((item, j) =>
                          i === j ? { ...item, [field]: e.target.value } : item,
                        ),
                      )
                    }
                  />
                ))}
              </div>
              <Button
                variant="ghost"
                aria-label={t("清除")}
                disabled={steps.length <= 1}
                onClick={() => setSteps((old) => old.filter((_, j) => i !== j))}
              >
                <X size={14} />
              </Button>
            </div>
          ))}
        </div>
        <div className="form-actions">
          <Button
            onClick={() =>
              setSteps((old) => [
                ...old,
                { name: "", action: "", transition: "" },
              ])
            }
          >
            <Plus size={14} />
            {t("添加步骤")}
          </Button>
          <Button
            variant="primary"
            disabled={steps.some((s) => !s.name.trim())}
            onClick={() =>
              void guarded(async () => {
                const result = await api<{ text: string }>(
                  "/sfc/requirement",
                  "POST",
                  { steps },
                );
                setText((old) => `${old}\n${result.text}`.trim());
                setModal("");
                setPanel("agent");
              })
            }
          >
            {t("应用到需求")}
          </Button>
        </div>
      </Modal>
    </div>
  );
}

function AcceptedMessage({
  kind,
  text,
  t,
}: {
  kind: string;
  text: string;
  t: (key: string) => string;
}) {
  let structured: Record<string, unknown> | null = null;
  try {
    const parsed = JSON.parse(text);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed))
      structured = parsed;
  } catch {
    /* Accepted prose is rendered verbatim. */
  }
  if (kind === "generation" && structured)
    return (
      <div className="accepted-content">
        <p>{t("候选内容已通过响应验收，请在待审批中查看校验结果与差异。")}</p>
        <details>
          <summary>{t("查看完整响应")}</summary>
          <pre>{text}</pre>
        </details>
      </div>
    );
  if (kind === "analysis" && structured)
    return (
      <div className="accepted-content">
        <p>{String(structured.summary || "")}</p>
        {["missing_info", "assumptions"].map((field) =>
          Array.isArray(structured[field]) && structured[field].length > 0 ? (
            <div key={field}>
              <strong>
                {t(field === "missing_info" ? "待补充信息" : "假设")}
              </strong>
              <DataView value={structured[field]} />
            </div>
          ) : null,
        )}
        <details>
          <summary>{t("查看完整响应")}</summary>
          <DataView value={structured} />
        </details>
      </div>
    );
  return <pre className="accepted-content">{text}</pre>;
}

function DiffView({ value, t }: { value: Json; t: (key: string) => string }) {
  if (!value || typeof value !== "object" || Array.isArray(value))
    return <DataView value={value} />;
  const diff = value as Record<string, Json>;
  const changes = Array.isArray(diff.changes)
    ? (diff.changes as Record<string, Json>[])
    : [];
  const comments = Array.isArray(diff.device_comment_changes)
    ? (diff.device_comment_changes as Record<string, Json>[])
    : [];
  return (
    <div className="candidate-diff">
      <h3>{t("差异数据")}</h3>
      {diff.has_changes === false ? (
        <p>{t("程序内容无变化")}</p>
      ) : typeof diff.unified_diff === "string" ? (
        <pre>{diff.unified_diff}</pre>
      ) : (
        <>
          <p>
            {t("网络")} {String(diff.before_network_count ?? 0)} →{" "}
            {String(diff.after_network_count ?? 0)}
          </p>
          {changes.map((change, i) => (
            <details key={i} open={changes.length === 1}>
              <summary>
                <span className="mono">
                  {String(change.marker)} {String(change.network)}
                </span>{" "}
                {String(change.comment || "")}
              </summary>
              <div className="diff-columns">
                <div>
                  <strong>{t("变更前")}</strong>
                  <DataView value={change.before} />
                </div>
                <div>
                  <strong>{t("变更后")}</strong>
                  <DataView value={change.after} />
                </div>
              </div>
            </details>
          ))}
          {comments.length > 0 && (
            <details open>
              <summary>{t("软元件注释变化")}</summary>
              <table>
                <thead>
                  <tr>
                    <th>{t("地址")}</th>
                    <th>{t("变更前")}</th>
                    <th>{t("变更后")}</th>
                  </tr>
                </thead>
                <tbody>
                  {comments.map((change, i) => (
                    <tr key={i}>
                      <td className="mono">{String(change.address)}</td>
                      <td>{String(change.before ?? "—")}</td>
                      <td>{String(change.after ?? "—")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          )}
          {diff.network_order_changed === true && (
            <DataView
              value={{
                before: diff.before_network_order,
                after: diff.after_network_order,
              }}
            />
          )}
          {!!diff.property_changes && (
            <DataView value={diff.property_changes} />
          )}
        </>
      )}
    </div>
  );
}

function DataView({ value }: { value: unknown }) {
  if (value === null || value === undefined)
    return <span className="muted">—</span>;
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  )
    return <span className="data-value">{String(value)}</span>;
  if (Array.isArray(value))
    return (
      <div className="data-list">
        {value.length ? (
          value.map((v, i) => (
            <div key={i}>
              <DataView value={v} />
            </div>
          ))
        ) : (
          <span className="muted">—</span>
        )}
      </div>
    );
  const entries = Object.entries(value as Record<string, unknown>);
  if (entries.length > 20)
    return <pre className="data-json">{stringify(value)}</pre>;
  return (
    <dl className="data-fields">
      {entries.map(([key, item]) => (
        <div key={key}>
          <dt>{fieldLabel(key)}</dt>
          <dd>
            <DataView value={item} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

function fieldLabel(key: string) {
  const labels: Record<string, [string, string, string]> = {
    summary: ["摘要", "Summary", "概要"],
    status: ["状态", "Status", "状態"],
    report_type: ["检查类型", "Review type", "検査種類"],
    report_id: ["报告编号", "Report ID", "レポートID"],
    base_version_id: ["基础版本", "Base version", "基準バージョン"],
    version_id: ["版本", "Version", "バージョン"],
    findings: ["检查发现", "Findings", "検出事項"],
    messages: ["校验说明", "Validation notes", "検証結果"],
    created_at: ["创建时间", "Created", "作成日時"],
    updated_at: ["更新时间", "Updated", "更新日時"],
    schema_version: ["格式版本", "Format version", "形式バージョン"],
    added: ["新增网络", "Added networks", "追加ネットワーク"],
    deleted: ["删除网络", "Removed networks", "削除ネットワーク"],
    modified: ["修改网络", "Changed networks", "変更ネットワーク"],
    changes: ["变更内容", "Changes", "変更内容"],
    before: ["变更前", "Before", "変更前"],
    after: ["变更后", "After", "変更後"],
    before_network_count: [
      "原网络数",
      "Original networks",
      "変更前ネットワーク数",
    ],
    after_network_count: [
      "候选网络数",
      "Candidate networks",
      "候補ネットワーク数",
    ],
    device_comments_changed: [
      "软元件注释变化",
      "Device comments changed",
      "デバイスコメント変更",
    ],
    severity: ["严重程度", "Severity", "重要度"],
    description: ["说明", "Description", "説明"],
    network: ["网络", "Network", "ネットワーク"],
    instruction_count: ["指令数", "Instructions", "命令数"],
    comment: ["注释", "Comment", "コメント"],
    passed: ["验证通过", "Passed", "検証合格"],
    valid: ["校验有效", "Valid", "有効"],
  };
  const index =
    document.documentElement.lang === "en"
      ? 1
      : document.documentElement.lang === "ja"
        ? 2
        : 0;
  return labels[key]?.[index] || key.replaceAll("_", " ");
}
