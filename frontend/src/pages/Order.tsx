import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, type AggregatedSlotEntry, type DateAvailabilityStatus, type OrderResponse, type Preset } from "../lib/api";
import PresetSelector from "../components/PresetSelector";

export default function OrderPage() {
  const [params, setParams] = useSearchParams();
  const [presets, setPresets] = useState<Preset[]>([]);
  const preset = Number(params.get("preset")) || 5;
  const requestedDate = params.get("date") || "";
  const [dates, setDates] = useState<DateAvailabilityStatus[]>([]);
  const [date, setDate] = useState("");
  const [slots, setSlots] = useState<AggregatedSlotEntry[]>([]);
  const [snapshot, setSnapshot] = useState<{ id: string; expires: string } | null>(null);
  const [selected, setSelected] = useState<AggregatedSlotEntry | null>(null);
  const [loading, setLoading] = useState(true);
  const [booking, setBooking] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<OrderResponse | null>(null);
  const [revision, setRevision] = useState(0);
  const attempt = useRef<{ key: string; id: string } | null>(null);
  const target = presets.find(item => item.index === preset);
  useEffect(() => { api.getPresets().then(data => setPresets(data.presets)).catch(error => setError(error.message)); }, []);
  useEffect(() => {
    let active = true;
    setLoading(true); setError(""); setDates([]); setDate(""); setSlots([]); setSelected(null); setResult(null);
    api.getImmediateAvailability({ preset }).then(data => {
      if (!active) return;
      const available = data.dates.filter(item => item.selectable);
      setDates(available); setDate(available.find(item => item.date === requestedDate)?.date || available[0]?.date || "");
    }).catch(error => { if (active) setError(error.message); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [preset, requestedDate, revision]);
  useEffect(() => {
    if (!date) return;
    let active = true;
    setLoading(true); setError(""); setSlots([]); setSelected(null); setSnapshot(null);
    api.getImmediateSlots({ preset, date, show_full: true }).then(data => {
      if (active) {
        setSlots(data.entries);
        setSnapshot(data.snapshot_id && data.expires_at ? { id: data.snapshot_id, expires: data.expires_at } : null);
      }
    })
      .catch(error => { if (active) setError(error.message); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [preset, date]);
  async function submit() {
    if (!selected) return;
    if (!snapshot || Date.now() >= Date.parse(snapshot.expires)) {
      setError("余位信息已过期，请刷新后重新选择时段。");
      return;
    }
    setBooking(true); setError(""); setResult(null);
    const key = JSON.stringify([preset, date, selected.start, selected.end, snapshot.id]);
    if (attempt.current?.key !== key) attempt.current = { key, id: crypto.randomUUID() };
    try {
      const response = await api.createOrder({ preset, date, start_time: selected.start, end_time: selected.end,
        request_id: attempt.current.id, snapshot_id: snapshot.id });
      setResult(response);
      if (["not_submitted", "rejected", "login_required", "challenge_required"].includes(response.status || "")) attempt.current = null;
      if (response.success) {
        setSelected(null);
        try {
          const data = await api.getImmediateSlots({ preset, date, show_full: true });
          setSlots(data.entries);
          setSnapshot(data.snapshot_id && data.expires_at ? { id: data.snapshot_id, expires: data.expires_at } : null);
        }
        catch { setError("预约已成功，但余位刷新失败。请在我的订单中核对结果。"); }
      }
    } catch (error) {
      setResult({ success: false, status: "unknown", request_id: attempt.current?.id,
        message: `连接未返回确认结果，请先核对订单。${(error as Error).message}` });
    }
    finally { setBooking(false); }
  }
  async function reconcile(confirmNotCreated = false) {
    if (!result?.request_id) return;
    if (confirmNotCreated && !window.confirm("请确认你已在官方订单页面核对，确实没有生成这笔预约。仅查询暂未显示订单不能排除它仍在处理。是否记录你的确认？")) return;
    setBooking(true); setError("");
    try {
      const response = await api.reconcileOrder(result.request_id, confirmNotCreated);
      setResult(response);
      if (response.success || response.status === "not_submitted") {
        attempt.current = null;
        setSelected(null);
      }
    } catch (error) { setError((error as Error).message); }
    finally { setBooking(false); }
  }
  return <>
    <div className="content-header"><div><h2>场地预约</h2><p className="content-subtitle">选好场馆和时段，在这里完成预约。</p></div><Link to="/orders" className="button button-secondary">查看我的订单 →</Link></div>
    <ol className="booking-steps" aria-label="预约流程"><li className="is-current">1 选择场馆</li><li className={date ? "is-current" : ""}>2 选择时段</li><li className={selected ? "is-current" : ""}>3 确认预约</li></ol>
    <section className="panel"><h3>选择场馆与运动</h3><PresetSelector presets={presets} value={preset} onChange={value => setParams({ preset: String(value) })} disabled={booking} /></section>
    {error && <div className="notice notice-error" role="alert">{error}<button className="button button-secondary" disabled={booking || loading} onClick={() => setRevision(value => value + 1)}>重新查询</button></div>}
    {result && <section className={`notice ${result.success ? "notice-success" : "notice-error"}`} role="status">
      <h3>{result.success ? "预约已提交成功" : result.status === "unknown" ? "预约结果待核对" : "预约未完成"}</h3>
      <p>{result.message}</p>{result.order_id && <p>订单号：{result.order_id}</p>}
      <Link to="/orders" className="button button-primary">查看订单与支付状态 →</Link>
      {result.status === "unknown" && result.request_id && <div className="choice-list">
        <button className="button button-secondary" disabled={booking} onClick={() => reconcile()}>重新核对订单</button>
        <a className="button button-secondary" href="https://sports.sjtu.edu.cn/pc/#/Order" target="_blank" rel="noreferrer">打开官方订单页面 ↗</a>
        <button className="button button-secondary" disabled={booking} onClick={() => reconcile(true)}>我已核对，确认未生成订单</button>
      </div>}
    </section>}
    <section className="panel" aria-busy={loading}><div className="content-header"><h3>选择日期与时段</h3><button className="button button-secondary" disabled={loading || booking} onClick={() => setRevision(value => value + 1)}>刷新余位</button></div>
      <div className="choice-list" aria-label="可预约日期">{dates.map(item => <button key={item.date} className={`choice-button${item.date === date ? " is-selected" : ""}`} aria-pressed={item.date === date} disabled={booking} onClick={() => { setDate(item.date); setResult(null); }}>{new Date(`${item.date}T00:00:00`).toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "short" })}</button>)}</div>
      {loading ? <p role="status">正在查询可预约时段…</p> : <>
        {!slots.some(slot => slot.available_count > 0) && <div className="empty-state"><h4>{dates.length ? "这个日期暂时没有余位" : "当前暂无开放的预约日期"}</h4><p>换一个日期或场馆，也可以创建余位监控。</p></div>}
        <div className="slot-choices">{slots.map(slot => <button key={`${slot.start}-${slot.end}`} className={`choice-button${selected === slot ? " is-selected" : ""}`} disabled={booking || slot.available_count <= 0} aria-pressed={selected === slot} onClick={() => { setSelected(slot); setResult(null); }}><strong>{slot.start}–{slot.end}</strong><span>{slot.available_count > 0 ? `余 ${slot.total_remain ?? slot.available_count}` : "已满"}{slot.min_price != null ? ` · ¥${slot.min_price}${slot.max_price !== slot.min_price ? `–${slot.max_price}` : ""}` : ""}</span></button>)}</div>
        <p className="muted-text">没有合适的时段？<Link to={`/monitor?preset=${preset}`}>为这个项目创建余位监控 →</Link></p>
      </>}
    </section>
    {selected && <section className="panel booking-confirm"><div><h3>确认这场运动</h3><p>{target?.venue_name} · {target?.field_type_name}</p><strong>{date} · {selected.start}–{selected.end}</strong><p className="muted-text">系统将分配该时段的可用场地；实际金额及支付要求以订单为准。</p></div><button className="button button-primary" disabled={booking || loading || result?.status === "unknown"} onClick={submit}>{booking ? "正在提交，请稍候…" : "确认预约"}</button></section>}
  </>;
}
