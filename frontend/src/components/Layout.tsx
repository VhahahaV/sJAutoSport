import type { PropsWithChildren } from "react";
import { NavLink, useLocation } from "react-router-dom";

const links = [
  { to: "/", label: "仪表盘", end: true, icon: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z" },
  { to: "/slots", label: "查询场地", icon: "M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14 M15 15l6 6" },
  { to: "/order", label: "立即预订", icon: "M5 5h14v16H5z M8 2v6 M16 2v6 M5 11h14 M9 16l2 2 4-4" },
  { to: "/orders", label: "订单管理", icon: "M6 3h12v18l-3-2-3 2-3-2-3 2z M9 8h6 M9 12h6" },
  { to: "/monitor", label: "监控任务", icon: "M3 12h4l3-8 4 16 3-8h4" },
  { to: "/schedule", label: "定时任务", icon: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M12 7v5l3 2" },
  { to: "/sessions", label: "会话管理", icon: "M12 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M4 21v-3a6 6 0 0 1 6-4h4a6 6 0 0 1 6 4v3" },
];

const Layout = ({ children }: PropsWithChildren) => {
  const { pathname } = useLocation();
  const currentPage = links.find((item) => item.to === pathname)?.label ?? "运动控制台";
  const today = new Date().toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "short" });

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">跳到主要内容</a>
      <aside className="sidebar">
        <NavLink to="/" className="brand" aria-label="SJTU Sports 首页">
          <img src="/favicon.svg" alt="" width="40" height="40" />
          <div>
            <span className="brand-name">SJTU SPORTS</span>
            <span className="brand-caption">让运动，轻松发生</span>
          </div>
        </NavLink>
        <div>
          <p className="nav-heading">我的运动空间</p>
          <nav className="nav-links" aria-label="主要导航">
            {links.map((item) => (
              <NavLink key={item.to} to={item.to} end={item.end}
                className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"
                  strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d={item.icon} />
                </svg>
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>
        <div className="sidebar-footer">
          <span className="sidebar-footer-mark" aria-hidden="true" />
          <strong>给日常，留一点运动。</strong>
          <p>场地和时间安排好，<br />把专注留给热爱。</p>
        </div>
      </aside>
      <main className="content" id="main-content">
        <header className="workspace-header">
          <div className="workspace-breadcrumb">
            <span>交大运动</span><span aria-hidden="true">/</span><strong>{currentPage}</strong>
          </div>
          <time className="workspace-date" dateTime={new Date().toLocaleDateString("en-CA")}>{today}</time>
        </header>
        <div className="workspace-content">{children}</div>
      </main>
    </div>
  );
};

export default Layout;
