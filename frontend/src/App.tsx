import { useCallback, useEffect, useState } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import Layout from "./components/Layout";
import DashboardPage from "./pages/Dashboard";
import LoginStatusPage from "./pages/LoginStatus";
import MonitorPage from "./pages/Monitor";
import OrderPage from "./pages/Order";
import OrdersPage from "./pages/Orders";
import KeepAlivePage from "./pages/KeepAlive";
import { api, type LoginStatusResponse } from "./lib/api";

export default function App() {
  const [status, setStatus] = useState<LoginStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const refresh = useCallback(async () => {
    setError("");
    try { setStatus(await api.getLoginStatus()); }
    catch (error) { setStatus(null); setError((error as Error).message); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => {
    void refresh();
    const expired = () => setStatus({ success: false, account: null });
    window.addEventListener("session-expired", expired);
    return () => window.removeEventListener("session-expired", expired);
  }, [refresh]);
  if (loading) return <main className="login-workspace"><section className="panel">正在连接登录服务…</section></main>;
  return <>
    {error && <div className="login-workspace notice notice-error" role="alert">{error}<button className="button button-secondary" onClick={refresh}>重新连接</button></div>}
    <Routes>
      <Route path="/" element={status?.success ? <Navigate to="/dashboard" replace /> : <LoginStatusPage onRefresh={refresh} />} />
      <Route path="/sessions" element={<Navigate to="/" replace />} />
      <Route path="/login-status" element={<Navigate to="/" replace />} />
      <Route path="*" element={status?.success ? <Layout><Routes>
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/slots" element={<OrderPage />} />
        <Route path="/order" element={<Navigate to="/slots" replace />} />
        <Route path="/orders" element={<OrdersPage />} />
        <Route path="/monitor" element={<MonitorPage />} />
        <Route path="/keep-alive" element={<KeepAlivePage />} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes></Layout> : <Navigate to="/" replace />} />
    </Routes>
  </>;
}
