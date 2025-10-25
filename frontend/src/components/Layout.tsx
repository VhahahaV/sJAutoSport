import type { PropsWithChildren } from "react";
import { NavLink } from "react-router-dom";

type NavItem = {
  to: string;
  label: string;
  end?: boolean;
};

const links: NavItem[] = [
  { to: "/", label: "仪表盘", end: true },
  { to: "/slots", label: "查询场地" },
  { to: "/order", label: "立即预订" },
  { to: "/monitor", label: "监控任务" },
  { to: "/schedule", label: "定时任务" },
  { to: "/sessions", label: "会话管理" },
];

const Layout = ({ children }: PropsWithChildren) => (
  <div className="app-shell">
    <aside className="sidebar">
      <div>
        <h1>SJTU Sports</h1>
        <p style={{ marginTop: "8px", color: "rgba(226, 232, 240, 0.7)" }}>
          自动化控制台
        </p>
      </div>
      <nav className="nav-links">
        {links.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              `nav-link${isActive ? " active" : ""}`
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
      <div style={{ marginTop: "auto", fontSize: "13px", opacity: 0.8 }}>
        <div>Made for efficient bookings</div>
      </div>
    </aside>
    <main className="content">
      <div className="floating-bubbles" aria-hidden>
        <span className="floating-bubble" style={{ left: "8%", top: "12%", animationDuration: "14s" }} />
        <span className="floating-bubble" style={{ left: "78%", top: "18%", animationDuration: "16s", animationDelay: "4s" }} />
        <span className="floating-bubble" style={{ left: "65%", top: "72%", animationDuration: "18s", animationDelay: "6s" }} />
        <span className="floating-bubble" style={{ left: "12%", top: "78%", animationDuration: "15s", animationDelay: "2s" }} />
      </div>
      {children}
    </main>
  </div>
);

export default Layout;
