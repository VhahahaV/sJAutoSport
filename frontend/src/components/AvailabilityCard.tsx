import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, type DashboardAvailability, type DashboardCardConfig, type DashboardDay, type Preset } from "../lib/api";

type Props = { card: DashboardCardConfig; preset?: Preset; revision: number; onRemove: (id: string) => Promise<void> };
const statusLabels: Record<DashboardDay["status"], string> = {
  available: "有余位", full: "暂无余位", closed: "未开放", unopened: "未开放", error: "查询失败",
};
const dateLabel = (date: string) => date.slice(5).replace("-", "/");

export default function AvailabilityCard({ card, preset, revision, onRemove }: Props) {
  const [data, setData] = useState<DashboardAvailability | null>(null);
  const [selectedDate, setSelectedDate] = useState("");
  const [busy, setBusy] = useState(true);
  const [removing, setRemoving] = useState(false);
  const [error, setError] = useState("");
  const [localRevision, setLocalRevision] = useState(0);
  const requestVersion = useRef(0);
  useEffect(() => {
    const version = ++requestVersion.current;
    setBusy(true); setError("");
    api.getDashboardAvailability(card.id).then(result => {
      if (version !== requestVersion.current) return;
      setData(result);
      setSelectedDate(previous => result.days.some(day => day.date === previous) ? previous : (result.days.find(day => day.slots.length)?.date || result.days[0]?.date || ""));
    }).catch(error => { if (version === requestVersion.current) setError(error.message); })
      .finally(() => { if (version === requestVersion.current) setBusy(false); });
    return () => { requestVersion.current++; };
  }, [card.id, revision, localRevision]);
  async function remove() {
    setRemoving(true);
    try { await onRemove(card.id); }
    catch (error) { setError((error as Error).message); setRemoving(false); }
  }
  const days = data?.days || [];
  const selected = days.find(day => day.date === selectedDate);
  const availableDays = days.filter(day => day.slots.length > 0).length;
  const totalSlots = days.reduce((sum, day) => sum + day.slots.length, 0);
  const max = Math.max(1, ...days.map(day => day.slots.length));
  const remainder = selected?.slots.reduce((sum, slot) => sum + (slot.remain ?? 0), 0) || 0;
  const unknownRemainder = selected?.slots.some(slot => slot.remain == null);
  const knownRemainder = selected?.slots.some(slot => slot.remain != null);
  const maxRemainder = Math.max(1, ...(selected?.slots.map(slot => slot.remain ?? 0) || []));
  const title = `${preset?.venue_name || "场馆"} · ${preset?.field_type_name || `项目 ${card.preset}`}`;
  return <article className="availability-card" aria-label={title} aria-busy={busy}>
    <header className="availability-card-header">
      <div><h3 title={title}>{title}</h3><p>含今天的未来 {card.days} 天</p></div>
      <div className="availability-card-tools">
        <button type="button" className="card-icon-button" aria-label={`刷新${title}`} title="刷新卡片" disabled={busy || removing} onClick={() => setLocalRevision(value => value + 1)}>↻</button>
        <button type="button" className="card-icon-button" aria-label={`删除${title}卡片`} title="删除卡片" disabled={removing} onClick={remove}>×</button>
      </div>
    </header>
    <div className="availability-card-body">
      {error && <p className="availability-error" role="alert">{error}{data ? "（以下为上次查询结果）" : "，请点击右上角刷新重试。"}</p>}
      {!data ? <div className="availability-placeholder" role="status">{busy ? "正在查询最新场地余位…" : "暂未获取到场地信息"}</div> : <>
        <div className="availability-metrics"><strong>{availableDays}<small> / {card.days} 天有余位</small></strong><span>{totalSlots} 个可预约场次</span></div>
        <div className="availability-chart-caption"><span>每天可预约场次</span><span>点击柱形查看当天详情</span></div>
        <div className="availability-chart" role="group" aria-label="各日期可预约场次数柱状图">
          {days.map(day => <button key={day.date} type="button" className={`availability-bar${day.date === selectedDate ? " is-selected" : ""} is-${day.status}`} aria-pressed={day.date === selectedDate} aria-label={`${dateLabel(day.date)}，${statusLabels[day.status]}，${day.slots.length} 个可预约场次`} onClick={() => setSelectedDate(day.date)}>
            <span className="availability-bar-value">{day.status === "error" ? "!" : ["closed", "unopened"].includes(day.status) ? "—" : day.slots.length}</span>
            <span className="availability-bar-track"><span style={{ height: `${day.slots.length / max * 100}%` }} /></span>
            <span className="availability-bar-date">{dateLabel(day.date)}</span>
          </button>)}
        </div>
        <div className="availability-chart-legend">0 无余位 · — 未开放 · ! 查询失败</div>
        <div className="availability-detail-heading"><strong>{selected ? dateLabel(selected.date) : ""} · {selected ? statusLabels[selected.status] : ""}</strong>{selected?.slots.length ? <span>{knownRemainder ? `余量合计 ${remainder}${unknownRemainder ? "（部分未提供）" : ""}` : "余量未提供"}</span> : null}</div>
        <div className="availability-slot-list" tabIndex={0} aria-label={`${selected ? dateLabel(selected.date) : ""}可用场次明细，可滚动查看全部`}>
          {selected?.slots.length ? <ul>{selected.slots.map((slot, index) => <li key={`${slot.slot_id}-${index}`}>
            <div><strong>{slot.start}–{slot.end}</strong><span>{slot.field_name || slot.area_name || "可用场地"}</span>{slot.remain != null && <span className="slot-quantity-track" aria-hidden="true"><span style={{ width: `${slot.remain / maxRemainder * 100}%` }} /></span>}</div>
            <div><strong>{slot.remain == null ? "可预约 · 余量未提供" : `余 ${slot.remain}`}</strong><span>{slot.price == null ? "价格以订单为准" : `¥${slot.price}`}</span></div>
          </li>)}</ul> : <p className={selected?.status === "error" ? "availability-error" : "muted-text"}>{selected?.message || (selected?.status === "full" ? "当天暂无空余场地，试试其他日期。" : "当天尚未开放预约。")}</p>}
        </div>
      </>}
    </div>
    <footer className="availability-card-footer"><span>{busy ? "正在更新…" : data ? `更新于 ${new Date(data.updated_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}` : "等待查询"}</span><Link to={`/slots?preset=${card.preset}${selected ? `&date=${selected.date}` : ""}`}>前往预约 →</Link></footer>
  </article>;
}
