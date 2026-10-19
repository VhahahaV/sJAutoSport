import type { PropsWithChildren } from "react";
import { NavLink, useLocation } from "react-router-dom";

const links = [
  { to: "/keep-alive", label: "账号与会话", group: "设置", icon: "M12 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M4 21v-3a6 6 0 0 1 6-4h4a6 6 0 0 1 6 4v3" },
  { to: "/dashboard", label: "总览", group: "运动", icon: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z" },
  { to: "/slots", label: "场地预约", group: "运动", icon: "M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14 M15 15l6 6" },
  { to: "/orders", label: "我的订单", group: "运动", icon: "M6 3h12v18l-3-2-3 2-3-2-3 2z M9 8h6 M9 12h6" },
  { to: "/monitor", label: "余位监控", group: "自动化", icon: "M3 12h4l3-8 4 16 3-8h4" },
];

const Layout = ({ children }: PropsWithChildren) => {
  const { pathname } = useLocation();
  const currentPage = links.find((item) => item.to === pathname)?.label ?? "运动控制台";
  const today = new Date().toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "short" });

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">跳到主要内容</a>
      <aside className="sidebar">
        <NavLink to="/dashboard" className="brand" aria-label="SJTU Sports 首页">
          <img src="/favicon.svg" alt="" width="40" height="40" />
          <div>
            <span className="brand-name">SJTU SPORTS</span>
            <span className="brand-caption">让运动，轻松发生</span>
          </div>
        </NavLink>
        <div>
          {["运动", "自动化", "设置"].map(group => <div key={group}>
            <p className="nav-heading">{group}</p>
            <nav className="nav-links" aria-label={group}>
              {links.filter(item => item.group === group).map(item => <NavLink key={item.to} to={item.to} end
                className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={item.icon} /></svg>
                {item.label}
              </NavLink>)}
            </nav>
          </div>)}
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
