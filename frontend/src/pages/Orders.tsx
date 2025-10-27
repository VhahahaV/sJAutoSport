import { useCallback, useEffect, useMemo, useState } from "react";

import { api, type UserSummary } from "../lib/api";

type OrderStatus = "1" | "2" | "7" | "8" | "all";

type OrderRecord = {
  pOrderid: string;
  orderstateid: string;
  venuename: string;
  venname: string;
  spaceInfo: string;
  ordercreatement: string;
  orderpaytime?: string;
  countprice: number;
  cancelOrder: boolean;
  name: string;
  userId: string;
};

const statusLabels: Record<string, string> = {
  "1": "预定成功",
  "2": "已取消",
  "7": "已使用",
  "8": "支付超时取消",
};

const OrdersPage = () => {
  const [users, setUsers] = useState<UserSummary[]>([]);
  const [orders, setOrders] = useState<OrderRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedStatus, setSelectedStatus] = useState<OrderStatus>("1");
  const [currentPage, setCurrentPage] = useState(1);
  const [total, setTotal] = useState(0);

  const loadOrders = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await api.getOrders(currentPage);
      if (data.success) {
        setOrders(data.orders || []);
        setTotal(data.total || 0);
      } else {
        setError(data.message || "获取订单失败");
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [currentPage]);

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

        {error && (
          <div className="panel notice notice-error">
            <strong>加载失败</strong>
            <span>{error}</span>
          </div>
        )}

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
                    <th>运动时间</th>
                    <th>下单时间</th>
                    <th>价格</th>
                    <th>状态</th>
                  </tr>
                </thead>
                <tbody>
                  {userOrders.map((order) => (
                    <tr key={order.pOrderid}>
                      <td>{order.venuename}</td>
                      <td>{order.venname}</td>
                      <td>{order.spaceInfo}</td>
                      <td>{order.ordercreatement}</td>
                      <td>¥{order.countprice.toFixed(2)}</td>
                      <td>
                        <span className={`chip ${order.orderstateid === "1" ? "chip-success" : ""}`}>
                          {statusLabels[order.orderstateid] || order.orderstateid}
                        </span>
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

      {total > 10 && (
        <div className="panel">
          <div style={{ display: "flex", gap: "12px", alignItems: "center" }}>
            <button
              className="button"
              onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
              disabled={currentPage === 1}
            >
              上一页
            </button>
            <span>
              第 {currentPage} 页 / 共 {Math.ceil(total / 10)} 页
            </span>
            <button
              className="button"
              onClick={() => setCurrentPage((p) => p + 1)}
              disabled={currentPage >= Math.ceil(total / 10)}
            >
              下一页
            </button>
          </div>
        </div>
      )}
    </>
  );
};

export default OrdersPage;

