import { Routes, Route, Navigate } from "react-router-dom";

import Layout from "./components/Layout";
import PasswordGate from "./components/PasswordGate";
import DashboardPage from "./pages/Dashboard";
import LoginStatusPage from "./pages/LoginStatus";
import MonitorPage from "./pages/Monitor";
import OrderPage from "./pages/Order";
import SchedulePage from "./pages/Schedule";
import SlotsPage from "./pages/Slots";

const App = () => (
  <PasswordGate>
    <Layout>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/sessions" element={<LoginStatusPage />} />
        <Route path="/login-status" element={<Navigate to="/sessions" replace />} />
        <Route path="/slots" element={<SlotsPage />} />
        <Route path="/order" element={<OrderPage />} />
        <Route path="/monitor" element={<MonitorPage />} />
        <Route path="/schedule" element={<SchedulePage />} />
      </Routes>
    </Layout>
  </PasswordGate>
);

export default App;
