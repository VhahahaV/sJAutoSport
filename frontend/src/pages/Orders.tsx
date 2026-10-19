import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type OrderRecord } from "../lib/api";

export default function OrdersPage() {
  const [orders, setOrders] = useState<OrderRecord[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [filter, setFilter] = useState("all");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const labels: Record<string, string> = { "1": "预订成功", "2": "已取消", "7": "已使用", "8": "支付超时取消" };
  async function load(current = page) {
    setBusy(true); setMessage("");
    try { const data = await api.getOrders(current, 20); setOrders(data.orders); setTotal(data.total); }
    catch (error) { setMessage((error as Error).message); } finally { setBusy(false); }
  }
  useEffect(() => { void load(page); }, [page]);
  async function cancel(order: OrderRecord) {
    if (!window.confirm(`确认取消订单 ${order.pOrderid}？`)) return;
    setBusy(true);
    try { const result = await api.cancelOrder(order.pOrderid); if (result.success) await load(); setMessage(result.message); }
    catch (error) { setMessage((error as Error).message); } finally { setBusy(false); }
  }
  const visibleOrders = orders.filter(order => filter === "all" || String(order.orderstateid) === filter);
  return <><div className="content-header"><div><h2>我的订单</h2><p className="content-subtitle">核对预约、支付和使用状态，或取消不再需要的预约。</p></div><button className="button button-secondary" onClick={() => load()} disabled={busy}>刷新订单</button></div>
    {message && <div className="notice" role="status">{message}</div>}
    <section className="panel" aria-busy={busy}><label className="field">订单状态<select value={filter} onChange={e => setFilter(e.target.value)}><option value="all">当前页全部订单</option>{Object.entries(labels).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></label>
      <table className="table"><thead><tr><th>场馆 / 项目</th><th>日期 / 时段</th><th>状态</th><th>金额</th><th>操作</th></tr></thead><tbody>{visibleOrders.map(order => <tr key={order.pOrderid}><td>{order.venuename}<br />{order.venname}</td><td>{order.scDate}<br />{order.spaceInfo}</td><td>{labels[order.orderstateid] || order.orderstateid}</td><td>¥{order.countprice}</td><td>{order.can_cancel ? <button className="button button-danger" onClick={() => cancel(order)} disabled={busy}>取消订单</button> : <span className="muted-text">不可取消</span>}</td></tr>)}</tbody></table>
      {!visibleOrders.length && <p className="muted-text">{busy ? "正在加载订单…" : orders.length ? "当前页没有符合此状态的订单，可切换状态或翻页查看。" : "暂无订单。"}</p>}<div className="panel-actions"><Link className="button button-secondary" to="/slots">预约新的场地 →</Link></div>
      <div className="panel-actions"><button className="button button-secondary" disabled={busy || page <= 1} onClick={() => setPage(page - 1)}>上一页</button><span>第 {page} 页 · 共 {total} 条</span><button className="button button-secondary" disabled={busy || page * 20 >= total} onClick={() => setPage(page + 1)}>下一页</button></div>
    </section>
  </>;
}
