import { useEffect, useState } from "react";
import { Plus, Trash2, GitBranch, FileUp, Download } from "lucide-react";
import { api, artifactUrl, key } from "../api/client";
import type { Proposal } from "../api/client";
import { Button } from "../components/ui";
import "./fbd.css";

type Port = { name: string; x: number; y: number };
type Node = { id: string; source_offset?: number; template: string; symbol: string; x: number; y: number; width?: number; height?: number; ports?: Port[] };
type Wire = { source_offset?: number; start?: number[]; end?: number[]; from?: string; to?: string; via?: number[][] };
type Label = { name: string; data_type?: string; kind?: string; class_name?: string; initial_value?: string; device?: string; iec_address?: string; comment?: string };
type DeclarationEdit = { upserts?: Label[]; renames?: Record<string, string>; remove?: string[] };
export type FBDModel = { schema_version: number; program: string; canvas_height?: number; nodes: Node[]; wires: Wire[];
  labels?: Record<string, Label[]>; declaration_edits?: Record<string, DeclarationEdit>; unknown_record_count?: number; issues?: { code: string; message: string }[] };
type CatalogNode = { template: string; kind: string; symbol: string; width: number; height: number; ports: Port[] };

const templateLabel = (key: string, t: (s: string) => string) => {
  const labels: Record<string, string> = { contact: "常开触点", contact_nc: "常闭触点", coil: "线圈", input: "输入值", output: "输出变量" };
  return labels[key] ? t(labels[key]) : key.replace("function_block:", "FB · ").replace("function:", "Function · ");
};

export const emptyFBD = (): FBDModel => ({ schema_version: 1, program: "1.Program.pou", canvas_height: 12, nodes: [], wires: [] });

export function FBDImport({ pid, vid, disabled, onProposal, t }: {
  pid: string; vid: string; disabled: boolean; onProposal: (proposal: Proposal) => Promise<void>; t: (s: string) => string;
}) {
  const [upload, setUpload] = useState<{ filename: string; data_base64: string } | null>(null);
  const [programs, setPrograms] = useState<string[]>([]), [program, setProgram] = useState("");
  const [error, setError] = useState(""), [busy, setBusy] = useState(false);
  async function read(file?: File) {
    if (!file) return;
    setError(""); setUpload(null); setPrograms([]); setBusy(true);
    try {
      if (file.size > 30 * 1024 * 1024) throw new Error(t("GXW 文件不能超过 30 MiB。"));
      const encoded = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(",")[1]); reader.onerror = reject; reader.readAsDataURL(file);
      });
      const value = { filename: file.name, data_base64: encoded };
      const info = await api<{ programs: string[] }>("/fbd/inspect", "POST", value);
      if (!info.programs.length) throw new Error(t("工程中没有可读取的 Program.pou。"));
      setUpload(value); setPrograms(info.programs); setProgram(info.programs[0]);
    } catch (e) { setError(String(e instanceof Error ? e.message : e)); }
    finally { setBusy(false); }
  }
  async function propose() {
    if (!upload) return;
    setBusy(true); setError("");
    try {
      const proposal = await api<Proposal>("/fbd/proposals", "POST", { operation: "import", project_id: pid,
        version_id: vid || null, request_id: key(), data_base64: upload.data_base64, program });
      await onProposal(proposal);
    } catch (e) { setError(String(e instanceof Error ? e.message : e)); }
    finally { setBusy(false); }
  }
  return <div className="form fbd-import">
    <p>{t("读取 GXW 文件并预览结构化梯形图/FBD；确认后保存为本地版本。")}</p>
    <label>{t("选择 GXW 工程")}<input type="file" accept=".gxw" disabled={disabled || busy} onChange={e => void read(e.target.files?.[0])} /></label>
    {upload && <label>{t("程序")}<select value={program} onChange={e => setProgram(e.target.value)}>{programs.map(p => <option key={p}>{p}</option>)}</select></label>}
    {error && <p role="alert" className="fbd-error">{error}</p>}
    <Button disabled={disabled || busy || !upload} variant="primary" onClick={() => void propose()}><FileUp size={15} />{t(busy ? "正在读取…" : "预览导入并保存")}</Button>
  </div>;
}

export function FBDPanel({ value, svg, pid, vid, readOnly, preview, onProposal, t }: {
  value: FBDModel; svg: string; pid: string; vid: string; readOnly: boolean; preview: boolean;
  onProposal: (proposal: Proposal) => Promise<void>; t: (s: string) => string;
}) {
  const [draft, setDraft] = useState<FBDModel>(() => structuredClone(value));
  const sourceKey = JSON.stringify(value);
  useEffect(() => { setDraft(JSON.parse(sourceKey)); }, [sourceKey]);
  const [section, setSection] = useState("diagram"), [catalog, setCatalog] = useState<CatalogNode[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState("contact"), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [from, setFrom] = useState(""), [to, setTo] = useState(""), [table, setTable] = useState(Object.keys(value.labels || {})[0] || "1.Labels.lh");
  const [zoom, setZoom] = useState(1), [page, setPage] = useState(0);
  const dirty = JSON.stringify(draft) !== JSON.stringify(value);
  const disabled = readOnly || preview || busy;
  useEffect(() => { let active = true; api<{ nodes: CatalogNode[] }>("/fbd/catalog").then(v => { if (active) setCatalog(v.nodes); }).catch(e => { if (active) setError(e.message); }); return () => { active = false; }; }, []);
  function change(edit: (model: FBDModel) => void) { setDraft(old => { const next = structuredClone(old); edit(next); return next; }); }
  const tableNames = [...new Set([...Object.keys(draft.labels || {"1.Labels.lh": [], "Global1.gh": []}), ...Object.keys(draft.declaration_edits || {})])];
  const edit = draft.declaration_edits?.[table] || {};
  const originalRows = (draft.labels?.[table] || []).filter(row => !edit.remove?.includes(row.name));
  const rows = originalRows.map(row => { const name = edit.renames?.[row.name] || row.name; return { ...row, name, ...edit.upserts?.find(item => item.name === name) }; });
  rows.push(...(edit.upserts || []).filter(item => !rows.some(row => row.name === item.name)));
  function updateLabel(row: Label, field: keyof Label, value: string) {
    change(d => {
      d.declaration_edits ||= {}; const patch = d.declaration_edits[table] ||= {};
      patch.upserts ||= [];
      if (field === "name") {
        const source = (d.labels?.[table] || []).find(r => (patch.renames?.[r.name] || r.name) === row.name);
        if (source) { patch.renames ||= {}; patch.renames[source.name] = value; }
        const item = patch.upserts.find(r => r.name === row.name); if (item) item.name = value;
      } else {
        let item = patch.upserts.find(r => r.name === row.name);
        if (!item) { item = { name: row.name }; patch.upserts.push(item); }
        item[field] = value;
      }
    });
  }
  function addWire() {
    const endpoint = (text: string) => {
      const dot = text.lastIndexOf("."); const node = draft.nodes.find(n => n.id === text.slice(0, dot));
      const port = (node?.ports || catalog.find(c => c.template === node?.template)?.ports)?.find(p => p.name === text.slice(dot + 1));
      return node && port ? [node.x + port.x, node.y + port.y] : null;
    };
    const a = endpoint(from), b = endpoint(to); if (!a || !b) return;
    change(d => d.wires.push({ from, to, ...(a[0] !== b[0] && a[1] !== b[1] ? { via: [[Math.floor((a[0]+b[0])/2), a[1]], [Math.floor((a[0]+b[0])/2), b[1]]] } : {}) }));
  }
  async function propose() {
    setBusy(true); setError("");
    try {
      const proposal = await api<Proposal>("/fbd/proposals", "POST", { operation: vid ? "edit" : "generate",
        project_id: pid, version_id: vid || null, request_id: key(), model: draft });
      await onProposal(proposal);
    } catch (e) { setError(String(e instanceof Error ? e.message : e)); }
    finally { setBusy(false); }
  }
  const endpoints = draft.nodes.flatMap(n => (n.ports || catalog.find(c => c.template === n.template)?.ports || []).map(p => ({ value: `${n.id}.${p.name}`, label: `${n.symbol} · ${p.name} (${n.id})` })));
  return <div className="fbd-panel">
    <div className="fbd-toolbar"><strong>{draft.program.replace(".Program.pou", "")} · FBD</strong><span className="muted">{draft.nodes.length} {t("对象")} · {draft.wires.length} {t("导线")}</span>
      <div className="fbd-toolbar-actions">{vid && !preview && <a className="button" href={artifactUrl(pid, vid, "gxw", true)}><Download size={14} />GXW</a>}
      {!preview && <Button disabled={disabled || !draft.nodes.length || (!!vid && !dirty)} variant="primary" onClick={() => void propose()}><GitBranch size={14} />{t("预览候选")}</Button>}</div>
    </div>
    <div className="fbd-sections">{[["diagram","图形"],["objects","对象"],["wires","连接"],["labels","声明"]].map(([id,label]) => <button className={section === id ? "active" : ""} key={id} onClick={() => setSection(id)}>{t(label)}</button>)}
      {dirty && <span>{t("草稿已修改，预览候选后检查图形。")}</span>}
    </div>
    {error && <p role="alert" className="fbd-error">{error}</p>}
    {section === "diagram" ? <div className="fbd-diagram"><div className="fbd-zoom"><Button onClick={() => setZoom(v => Math.max(.25, v-.25))}>−</Button><span>{Math.round(zoom*100)}%</span><Button onClick={() => setZoom(v => Math.min(4, v+.25))}>+</Button></div>
      {svg ? <img alt={t("结构化梯形图/FBD")} src={svg} style={{ width: `${zoom*100}%`, minWidth: `${1100*zoom}px`, maxWidth: "none" }} /> : <div className="empty-state"><GitBranch size={38} /><h2>{t("生成 FBD 工程")}</h2><p>{t("在右侧描述需求并选择“生成程序”，或在对象和连接页签中创建程序。")}</p><Button onClick={() => setSection("objects")}>{t("添加对象")}</Button></div>}
    </div> : section === "objects" ? <div className="fbd-sheet">
      <div className="fbd-inline"><select aria-label={t("对象类型")} value={selectedTemplate} onChange={e => setSelectedTemplate(e.target.value)}>{catalog.map(c => <option key={c.template} value={c.template}>{templateLabel(c.template, t)}</option>)}</select>
        <Button disabled={disabled} onClick={() => change(d => { const c = catalog.find(c => c.template === selectedTemplate); if (c) d.nodes.push({ id: `node_${key().replaceAll("-", "")}`, template: c.template, symbol: c.symbol || (c.kind === "function_block" ? `FB_${d.nodes.length+1}` : c.kind === "coil" || c.kind === "output" ? "Y0" : "X0"), x: 3, y: 2+d.nodes.length*5 }); })}><Plus size={14}/>{t("添加对象")}</Button></div>
      <table><thead><tr>{["类型", "设备或实例名", "列", "行", "端口", ""].map((v,i) => <th key={i}>{t(v)}</th>)}</tr></thead><tbody>{draft.nodes.map((node, i) => <tr key={node.id}>
        <td><select disabled={disabled} value={node.template} onChange={e => change(d => { const c = catalog.find(c => c.template === e.target.value)!; d.nodes[i].template = c.template; if (c.symbol) d.nodes[i].symbol = c.symbol; delete d.nodes[i].ports; delete d.nodes[i].width; delete d.nodes[i].height; })}>{!catalog.some(c => c.template === node.template) && <option>{node.template}</option>}{catalog.map(c => <option key={c.template} value={c.template}>{templateLabel(c.template, t)}</option>)}</select></td>
        <td><input aria-label={`${t("设备或实例名")} ${i+1}`} disabled={disabled || node.template.startsWith("function:")} value={node.symbol} onChange={e => change(d => { d.nodes[i].symbol = e.target.value; })}/></td>
        {(["x","y"] as const).map(coord => <td key={coord}><input aria-label={`${node.id} ${coord}`} className="fbd-number" type="number" min="0" disabled={disabled} value={node[coord]} onChange={e => change(d => { d.nodes[i][coord] = Number(e.target.value); })}/></td>)}
        <td className="mono">{(node.ports || catalog.find(c => c.template === node.template)?.ports || []).map(p => p.name).join(" · ")}</td>
        <td><Button aria-label={`${t("删除对象")} ${i+1}`} disabled={disabled} onClick={() => change(d => { d.nodes.splice(i,1); d.wires = d.wires.filter(w => !w.from?.startsWith(node.id+".") && !w.to?.startsWith(node.id+".")); })}><Trash2 size={14}/></Button></td></tr>)}</tbody></table>
      <p className="muted">{t("移动对象后请在连接页签检查导线坐标。更换 FB 实例名会创建相应声明；旧声明可在声明页签中重命名或删除。")}</p>
    </div> : section === "wires" ? <div className="fbd-sheet"><div className="fbd-inline">
      <select aria-label={t("起点端口")} value={from} onChange={e => setFrom(e.target.value)}><option value="">{t("起点端口")}</option>{endpoints.map(e => <option key={e.value} value={e.value}>{e.label}</option>)}</select><span>→</span>
      <select aria-label={t("终点端口")} value={to} onChange={e => setTo(e.target.value)}><option value="">{t("终点端口")}</option>{endpoints.map(e => <option key={e.value} value={e.value}>{e.label}</option>)}</select>
      <Button disabled={disabled || !from || !to || from===to} onClick={addWire}><Plus size={14}/>{t("连接端口")}</Button>
      <Button disabled={disabled} onClick={() => change(d => d.wires.push({ start: [1,0], end: [1,d.canvas_height || 12] }))}>{t("添加左母线")}</Button></div>
      <table><thead><tr><th>{t("起点")}</th><th>{t("终点")}</th><th>{t("折点")}</th><th/></tr></thead><tbody>{draft.wires.map((w,i) => <tr key={i}>{(["start","end"] as const).map((field,side) => <td key={field}>{w[field] ? <div className="fbd-inline">{[0,1].map(coord => <input key={coord} className="fbd-number" type="number" min="0" aria-label={`${t("导线")} ${i+1} ${field} ${coord}`} disabled={disabled} value={w[field]![coord]} onChange={e => change(d => { d.wires[i][field]![coord] = Number(e.target.value); })}/>)}</div> : <span className="mono">{side ? w.to : w.from}</span>}</td>)}
      <td className="mono">{w.via?.map(p => p.join(",")).join(" → ") || "—"}</td><td><Button disabled={disabled} aria-label={`${t("删除导线")} ${i+1}`} onClick={() => change(d => { d.wires.splice(i,1); })}><Trash2 size={14}/></Button></td></tr>)}</tbody></table></div>
      : <div className="fbd-sheet"><div className="fbd-inline"><select aria-label={t("声明表")} value={table} onChange={e => { setTable(e.target.value); setPage(0); }}>{tableNames.map(n => <option key={n}>{n}</option>)}</select><Button disabled={disabled} onClick={() => change(d => { d.declaration_edits ||= {}; const p = d.declaration_edits[table] ||= {}; p.upserts ||= []; let index = rows.length+1; while(rows.some(r => r.name===`label_${index}`)) index++; p.upserts.push({ name:`label_${index}`, data_type:"BOOL", kind:"variable", class_name: table.endsWith(".gh") ? "VAR_GLOBAL" : "VAR" }); })}><Plus size={14}/>{t("添加声明")}</Button></div>
      <table><thead><tr>{["名称","数据类型","类别","初始值","软元件","注释", ""].map((v,i) => <th key={i}>{t(v)}</th>)}</tr></thead><tbody>{rows.slice(page*50,(page+1)*50).map((row,i) => <tr key={page*50+i}>{(["name","data_type","class_name","initial_value","device","comment"] as const).map(field => <td key={field}><input disabled={disabled} aria-label={`${row.name} ${field}`} value={row[field] || ""} onChange={e => updateLabel(row,field,e.target.value)}/></td>)}<td><Button disabled={disabled} aria-label={`${t("删除声明")} ${row.name}`} onClick={() => change(d => { d.declaration_edits ||= {}; const p=d.declaration_edits[table] ||= {}; const source=d.labels?.[table]?.find(r => (p.renames?.[r.name] || r.name)===row.name); if(source) { p.remove ||= []; p.remove.push(source.name); if(p.renames) delete p.renames[source.name]; } p.upserts=p.upserts?.filter(r => r.name!==row.name); })}><Trash2 size={14}/></Button></td></tr>)}</tbody></table>
      <div className="fbd-inline"><Button disabled={page===0} onClick={() => setPage(p=>p-1)}>{t("上一页")}</Button><span>{page+1} / {Math.max(1,Math.ceil(rows.length/50))} · {rows.length}</span><Button disabled={(page+1)*50>=rows.length} onClick={() => setPage(p=>p+1)}>{t("下一页")}</Button></div>
      <p className="muted">{t("FB 调用的实例与类型自动同步到声明表。未知声明字段和未知对象会保留；编译结果以 GX Works2 为准。")}</p></div>}
  </div>;
}
