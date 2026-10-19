import { FormEvent, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, type MonitorInfo, type Preset, type SlotAvailability } from "../lib/api";
import PresetSelector from "../components/PresetSelector";

function numbers(value: string, max: number) {
  if (!value.trim()) return undefined;
  const values = value.split(",").map(s => Number(s.trim()));
  if (values.some(n => !Number.isInteger(n) || n < 0 || n > max)) throw new Error(`请输入 0–${max} 之间的整数，用英文逗号分隔。`);
  return [...new Set(values)];
}

export default function MonitorPage() {
  const [params] = useSearchParams();
  const [showCreate, setShowCreate] = useState(params.has("preset"));
  const [presets, setPresets] = useState<Preset[]>([]);
  const [preset, setPreset] = useState<number | "">("");
  const [monitors, setMonitors] = useState<MonitorInfo[]>([]);
  const [interval, setInterval] = useState(240);
  const [hours, setHours] = useState("19,20");
  const [days, setDays] = useState("1");
  const [autoBook, setAutoBook] = useState(false);
  const [longRunning, setLongRunning] = useState(false);
  const [operatingStart, setOperatingStart] = useState(0);
  const [operatingEnd, setOperatingEnd] = useState(24);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function load() { const data = await api.listMonitors(); setMonitors(data.monitors); }
  useEffect(() => { Promise.all([api.getPresets(), api.listMonitors()]).then(([data, result]) => { setPresets(data.presets); setPreset(data.presets.find(p => p.index === Number(params.get("preset")))?.index || data.presets.find(p => p.index === 5)?.index || data.presets[0]?.index || ""); setMonitors(result.monitors); setLoaded(true); }).catch(error => setError(error.message)); }, []);
  useEffect(() => { const timer = window.setInterval(() => { void load().catch(error => setError(error.message)); }, 30000); return () => window.clearInterval(timer); }, []);
  async function create(event: FormEvent) {
    event.preventDefault(); if (preset === "") return; setBusy(true); setError("");
    try { if (hours.split(",").some(part => part.trim() === "") && hours.trim()) throw new Error("小时列表中有空项，请检查逗号。"); if (days.split(",").some(part => part.trim() === "") && days.trim()) throw new Error("日期列表中有空项，请检查逗号。"); if (operatingStart >= operatingEnd) throw new Error("每日检查结束时间必须晚于开始时间。"); if (autoBook && !window.confirm("该监控会在发现余位后自动创建真实预约订单，确认开启？")) return; await api.createMonitor({ monitor_id: `monitor-${crypto.randomUUID()}`, preset, interval_seconds: interval, preferred_hours: numbers(hours, 23), preferred_days: numbers(days, 8), auto_book: autoBook, long_running: longRunning, operating_start_hour: operatingStart, operating_end_hour: operatingEnd }); await load(); setShowCreate(false); }
    catch (error) { setError((error as Error).message); } finally { setBusy(false); }
  }
  async function action(id: string, action: "pause" | "resume" | "delete") {
    if (action === "delete" && !window.confirm("确认删除这个监控？删除后将停止检查余位。")) return;
    setBusy(true); setError("");
    try { if (action === "pause") await api.pauseMonitor(id); else if (action === "resume") await api.resumeMonitor(id); else await api.deleteMonitor(id); await load(); }
    catch (error) { setError((error as Error).message); } finally { setBusy(false); }
  }
  return <><div className="content-header"><div><h2>实时余位监控</h2><p className="content-subtitle">持续检查期望的日期和时段。发现结果保存在本地，当前未接入外部消息推送。</p></div><div className="panel-actions"><button className="button button-secondary" onClick={() => load().catch(error => setError(error.message))} disabled={busy}>刷新状态</button><button className="button button-primary" onClick={() => setShowCreate(value => !value)} disabled={busy}>{showCreate ? "收起创建表单" : "新建监控"}</button></div></div>
    {error && <div className="notice notice-error" role="alert">{error}</div>}
    <p className="notice">监控与预约不同：它会持续查找余位。需要长期运行时，请先到<Link to="/keep-alive">账号与会话</Link>开启保活。</p>
    {showCreate && <section className="panel"><h3>新建余位监控</h3><form className="form-grid" onSubmit={create}>
      <PresetSelector presets={presets} value={preset} onChange={setPreset} />
      <label className="field">检查间隔（秒）<input type="number" min={30} value={interval} onChange={e => setInterval(Number(e.target.value))} required /></label>
      <label className="field">期望开始小时（英文逗号分隔）<input value={hours} onChange={e => setHours(e.target.value)} placeholder="19,20" /></label>
      <label className="field">未来第几天（0 今天，1 明天）<input value={days} onChange={e => setDays(e.target.value)} placeholder="1,2" /></label>
      <details className="monitor-advanced"><summary>高级选项：自动预约与每日检查范围</summary><div className="form-grid">
      <label className="field">每天从几点开始检查<input type="number" min={0} max={23} value={operatingStart} onChange={e => setOperatingStart(Number(e.target.value))} /></label>
      <label className="field">每天几点停止检查<input type="number" min={1} max={24} value={operatingEnd} onChange={e => setOperatingEnd(Number(e.target.value))} /></label>
      <label className="field"><span>发现余位后自动预约（会创建真实订单）</span><input type="checkbox" checked={autoBook} onChange={e => { setAutoBook(e.target.checked); if (!e.target.checked) setLongRunning(false); }} /></label>
      {autoBook && <label className="field"><span>预约成功后继续监控其他日期</span><input type="checkbox" checked={longRunning} onChange={e => setLongRunning(e.target.checked)} /></label>}
      </div></details>
      <div className="form-actions"><button className="button button-primary" disabled={busy || preset === ""}>创建监控</button></div>
    </form></section>}
    <section className="panel"><h3>我的监控</h3>{!monitors.length && <p className="muted-text">{loaded ? "暂无监控。点击“新建监控”，选择想去的场馆和时间。" : "正在读取监控…"}</p>}{monitors.map(info => { const id = String(info.id); const found = (Array.isArray(info.found_slots) ? info.found_slots : []) as SlotAvailability[]; const resolved = info.resolved as { label?: string } | undefined; return <article className="panel" key={id}><h4>{resolved?.label || `预设 ${info.preset}`}</h4><p>{({ running: "运行中", paused: "已暂停", completed: "已完成", error: "异常", stopped: "已停止" } as Record<string, string>)[String(info.status)] || String(info.status)} · 最近检查：{info.last_check ? new Date(String(info.last_check)).toLocaleString() : "等待检查"}</p><p className="muted-text">{info.auto_book ? "发现后自动预约" : "只检查余位"} · 每 {String(info.interval_seconds || 240)} 秒检查 · 未来第 {Array.isArray(info.preferred_days) ? info.preferred_days.join("、") : "任意"} 天 · {Array.isArray(info.preferred_hours) ? info.preferred_hours.map(hour => `${hour}点`).join("、") : "任意时段"}</p><p className="muted-text">已发现 {Array.isArray(info.found_slots) ? info.found_slots.length : 0} 个时段 · 成功预约 {Number(info.successful_bookings || 0)} 次</p>{found.length > 0 && <details><summary>查看最近发现的 {found.length} 个时段</summary><ul>{found.map((entry, index) => <li key={index}>{entry.date} · {entry.slot.start}–{entry.slot.end} · {entry.slot.field_name || entry.slot.area_name || "可用场地"} · 余 {entry.slot.remain ?? "可预约"}</li>)}</ul></details>}{info.last_error ? <p className="notice notice-error">{String(info.last_error)}</p> : null}<div className="panel-actions"><Link className="button button-secondary" to={`/slots?preset=${info.preset}`}>查看场地并预约</Link>{info.status === "running" && <button className="button button-secondary" disabled={busy} onClick={() => action(id, "pause")}>暂停</button>}{info.status === "paused" && <button className="button button-secondary" disabled={busy} onClick={() => action(id, "resume")}>恢复</button>}<button className="button button-danger" disabled={busy} onClick={() => action(id, "delete")}>删除</button></div></article>; })}</section>
  </>;
}
