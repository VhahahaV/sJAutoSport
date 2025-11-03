import { useCallback, useEffect, useMemo, useState } from "react";

import { api, type OrderRecord } from "../lib/api";

type OrderStatus = "1" | "2" | "7" | "8" | "all";

const statusLabels: Record<string, string> = {
  "1": "预定成功",
  "2": "已取消",
  "7": "已使用",
  "8": "支付超时取消",
};

const OrdersPage = () => {
  const [orders, setOrders] = useState<OrderRecord[]>([]);
  const [summaries, setSummaries] = useState<
    Array<{
      userId: string;
      name: string;
      count: number;
      error?: string;
    }>
  >([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedStatus, setSelectedStatus] = useState<OrderStatus>("1");
  const [message, setMessage] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState<Record<string, boolean>>({});
  const total = orders.length;

  const loadOrders = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await api.getOrders(1, 100);
      if (data.success) {
        const records = data.orders || [];
        setOrders(records);
        setSummaries(data.summary || []);
      } else {
        setError(data.message || "获取订单失败");
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadOrders();
  }, [loadOrders]);

  // 按用户分组订单
  const ordersByUser = useMemo(() => {
    const grouped: Record<string, OrderRecord[]> = {};
    for (const order of orders) {
      const key = order.userId;
      if (!grouped[key]) {
        grouped[key] = [];
      }
      grouped[key].push(order);
    }
    return grouped;
  }, [orders]);

  // 筛选订单
  const filteredOrdersByUser = useMemo(() => {
    const filtered: Record<string, OrderRecord[]> = {};
    for (const [userId, userOrders] of Object.entries(ordersByUser)) {
      const filteredOrders = userOrders.filter((order) => {
        if (selectedStatus === "all") {
          return true;
        }
        return order.orderstateid === selectedStatus;
      });
      if (filteredOrders.length > 0) {
        filtered[userId] = filteredOrders;
      }
    }
    return filtered;
  }, [ordersByUser, selectedStatus]);

  const handleCancel = useCallback(
    async (order: OrderRecord) => {
      if (!order?.pOrderid) {
        return;
      }
      if (!confirm(`确认要取消订单 ${order.pOrderid} 吗？`)) {
        return;
      }
      const orderId = order.pOrderid;
      setCancelling((prev) => ({ ...prev, [orderId]: true }));
      setError(null);
      setMessage(null);
      try {
        const result = await api.cancelOrder(orderId, order.userId);
        await loadOrders();
        setMessage(result.message || "取消订单请求已提交");
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setCancelling((prev) => {
          const next = { ...prev };
          delete next[orderId];
          return next;
        });
      }
    },
    [loadOrders],
  );

  const formatDateLabel = (raw?: string | null) => {
    if (!raw) return "-";
    const text = raw.trim();
    if (!text) return "-";
    const iso = text.length >= 10 ? text.slice(0, 10).replace(/\//g, "-") : text;
    const parts = iso.split("-");
    if (parts.length >= 3) {
      const month = parts[1]?.padStart(2, "0");
      const day = parts[2]?.padStart(2, "0");
      if (month && day) {
        return `${month}-${day}`;
      }
    }
    return text;
  };

  const extractStartTime = (raw?: string | null) => {
    if (!raw) return "-";
    const text = raw.trim();
    if (!text) return "-";
    const match = text.match(/\b(\d{1,2}:\d{2})/);
    if (match) {
      const hour = match[1].split(":")[0]?.padStart(2, "0");
      return hour ? `${hour}:00` : match[1];
    }
    return text;
  };

  return (
    <>
      <div className="content-header">
        <div>
          <h2>订单管理</h2>
          <p className="content-subtitle">查看和管理所有用户的订单信息。</p>
        </div>
      </div>

      <div className="panel">
        <div style={{ display: "flex", gap: "12px", alignItems: "center", flexWrap: "wrap", marginBottom: "16px" }}>
          <label style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span>筛选状态：</span>
            <select
              value={selectedStatus}
              onChange={(e) => setSelectedStatus(e.target.value as OrderStatus)}
              className="input"
              style={{ minWidth: "150px" }}
            >
              <option value="all">全部</option>
              <option value="1">预定成功</option>
              <option value="2">已取消</option>
              <option value="7">已使用</option>
              <option value="8">支付超时取消</option>
            </select>
          </label>
          <span className="muted-text">共 {total} 条订单</span>
        </div>

        {summaries.length > 0 && (
          <div className="muted-text" style={{ display: "flex", gap: "12px", flexWrap: "wrap" }}>
            {summaries.map((item) => {
              const displayError =
                item.error && item.error.length > 80 ? `${item.error.slice(0, 77)}...` : item.error;
              return (
                <span key={item.userId}>
                  {item.name}: {item.count} 条{displayError ? `（同步失败：${displayError}）` : ""}
                </span>
              );
            })}
          </div>
        )}

        {error && (
          <div className="panel notice notice-error">
            <strong>加载失败</strong>
            <span>{error}</span>
          </div>
        )}

        {message ? (
          <div className="panel">
            <strong>提示</strong>
            <span>{message}</span>
          </div>
        ) : null}

        {loading && <span className="muted-text">加载订单中…</span>}

        {!loading && Object.keys(filteredOrdersByUser).length === 0 && (
          <span className="muted-text">暂无订单数据。</span>
        )}
      </div>

      {Object.entries(filteredOrdersByUser).map(([userId, userOrders]) => (
        <section key={userId} className="section">
          <h3>用户：{userId} ({userOrders[0]?.name || userId})</h3>
          <div className="panel">
            <div className="table-container">
              <table className="table">
                <thead>
                  <tr>
                    <th>场馆</th>
                    <th>运动类型</th>
                    <th>开始时间</th>
                    <th>预约日期</th>
                    <th>状态</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {userOrders.map((order) => (
                    <tr key={order.pOrderid}>
                      <td>{order.venuename}</td>
                      <td>{order.venname}</td>
                      <td>{extractStartTime(order.spaceInfo)}</td>
                      <td>{formatDateLabel(order.scDate || order.ordercreatement)}</td>
                      <td>
                        <span className={`chip ${order.orderstateid === "1" ? "chip-success" : ""}`}>
                          {statusLabels[order.orderstateid] || order.orderstateid}
                        </span>
                      </td>
                      <td>
                        {order.orderstateid === "1" ? (
                          <button
                            className="button button-danger"
                            type="button"
                            onClick={() => void handleCancel(order)}
                            disabled={Boolean(cancelling[order.pOrderid])}
                            style={{ minWidth: "140px" }}
                          >
                            {cancelling[order.pOrderid] ? "取消中..." : "取消订单"}
                          </button>
                        ) : (
                          <span className="muted-text">-</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      ))}
      
      {Object.keys(filteredOrdersByUser).length === 0 && !loading && (
        <div className="panel">
          <span className="muted-text">暂无符合条件的订单数据。</span>
        </div>
      )}

    </>
  );
};

export default OrdersPage;
