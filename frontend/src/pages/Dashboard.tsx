import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type DashboardCardConfig, type Preset } from "../lib/api";
import AvailabilityCard from "../components/AvailabilityCard";
import PresetSelector from "../components/PresetSelector";

export default function DashboardPage() {
  const [cards, setCards] = useState<DashboardCardConfig[]>([]);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [preset, setPreset] = useState<number | "">("");
  const [days, setDays] = useState(3);
  const [adding, setAdding] = useState(false);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    Promise.all([api.getDashboardCards(), api.getPresets()]).then(([saved, data]) => {
      if (!active) return;
      setCards(saved); setPresets(data.presets);
      setPreset(data.presets.find(item => item.index === 5)?.index || data.presets[0]?.index || "");
    }).catch(error => { if (active) setError(error.message); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);
  async function add(event: FormEvent) {
    event.preventDefault(); if (preset === "") return;
    setAdding(true); setError("");
    try { const card = await api.addDashboardCard({ preset, days }); setCards(previous => [...previous, card]); setShowAdd(false); }
    catch (error) { setError((error as Error).message); } finally { setAdding(false); }
  }
  async function remove(id: string) {
    await api.deleteDashboardCard(id);
    setCards(previous => previous.filter(card => card.id !== id));
  }
  return <>
    <div className="content-header dashboard-heading">
      <div><h2>我的场地看板</h2><p className="content-subtitle">每次进入自动更新。选一个日期，查看具体空余时段与余量。</p></div>
      <div className="panel-actions"><button className="button button-secondary" disabled={loading || !cards.length} onClick={() => setRevision(value => value + 1)}>刷新全部</button><button className="button button-primary" disabled={loading} onClick={() => setShowAdd(value => !value)}>{showAdd ? "收起" : "+ 添加卡片"}</button></div>
    </div>
    <nav className="dashboard-shortcuts" aria-label="快捷操作"><Link to="/slots">场地预约 ↗</Link><Link to="/orders">我的订单 →</Link><Link to="/monitor">余位监控 →</Link></nav>
    {error && <p className="notice notice-error" role="alert">{error}</p>}
    {showAdd && <section className="panel"><h3>添加场地卡片</h3><form className="form-grid" onSubmit={add}>
      <PresetSelector presets={presets} value={preset} onChange={setPreset} disabled={adding} />
      <label className="field">查询范围<select value={days} onChange={event => setDays(Number(event.target.value))} disabled={adding}>{Array.from({ length: 7 }, (_, index) => index + 1).map(value => <option key={value} value={value}>{value === 1 ? "今天" : `未来 ${value} 天（含今天）`}</option>)}</select></label>
      <p className="muted-text">卡片配置会保存；每次进入总览或点击刷新时获取最新余位。</p>
      <div className="form-actions"><button className="button button-primary" disabled={adding || preset === ""}>{adding ? "正在添加…" : "添加到看板"}</button></div>
    </form></section>}
    {loading ? <p role="status">正在载入你的看板…</p> : cards.length ? <div className="availability-grid">{cards.map(card => <AvailabilityCard key={card.id} card={card} preset={presets.find(item => item.index === card.preset)} revision={revision} onRemove={remove} />)}</div> : !error && <section className="panel dashboard-empty"><h3>先把常去的场地放在这里</h3><p>选择场馆、运动和 1–7 天的查询范围，随时查看哪里有空。</p><button className="button button-primary" onClick={() => setShowAdd(true)}>添加第一张卡片</button></section>}
  </>;
}
