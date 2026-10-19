import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import StatusCard from "../components/StatusCard";
import SlotTable from "../components/SlotTable";
import SportsIllustration from "../components/SportsIllustration";
import { api, type HealthResponse, type JobSummary, type LoginStatusResponse, type Preset } from "../lib/api";

const JobDeleteButton = ({ job, onDeleted }: { job: JobSummary; onDeleted: () => void }) => {
  const [loading, setLoading] = useState(false);
  
  const handleDelete = async () => {
    if (!confirm(`确定要删除任务"${job.name}"吗？`)) {
      return;
    }
    
    try {
      setLoading(true);
      if (job.job_type === "monitor") {
        const monitorId = job.job_id.replace("monitor:", "");
        await api.deleteMonitor(monitorId);
      } else if (job.job_type === "schedule") {
        const scheduleId = job.job_id.replace("schedule:", "");
        await api.deleteSchedule(scheduleId);
      } else if (job.job_type === "keep_alive") {
        await api.deleteKeepAliveJob(job.job_id);
      }
      onDeleted();
    } catch (err) {
      alert((err as Error).message);
    } finally {
      setLoading(false);
    }
  };
  
  return (
    <button
      className="button button-danger"
      onClick={handleDelete}
      disabled={loading}
      style={{ padding: "4px 12px", fontSize: "12px" }}
    >
      {loading ? "..." : "删除"}
    </button>
  );
};

const jobTypeLabels: Record<string, string> = {
  monitor: "监控",
  schedule: "定时",
  auto_booking: "自动抢票",
  keep_alive: "会话保活",
};

const DashboardPage = () => {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [jobsLoading, setJobsLoading] = useState(true);
  const [jobTypeFilter, setJobTypeFilter] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [loginStatus, setLoginStatus] = useState<LoginStatusResponse | null>(null);

  // 默认查询的预设 (气模体育中心羽毛球、学生中心健身房、子衿街健身房)
  const dashboardPresets = [
    { index: 5, label: "气膜羽毛球" },
    { index: 18, label: "霍体羽毛球" },
    { index: 3, label: "学活健身房" },
    { index: 8, label: "子衿街健身房" },
    { index: 20, label: "霍体健身房" },
    { index: 2, label: "学活台球" },
  ];

  useEffect(() => {
    let mounted = true;
    const loadHealth = async () => {
      try {
        const [healthResp, presetsResp, loginResp] = await Promise.all([
          api.getHealth(),
          api.getPresets(),
          api.getLoginStatus(),
        ]);
        if (!mounted) return;
        setHealth(healthResp);
        setPresets(presetsResp.presets || []);
        setLoginStatus(loginResp);
      } catch (err) {
        if (mounted) {
          setError((err as Error).message);
        }
      }
    };
    loadHealth();
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    let mounted = true;
    const loadJobs = async () => {
      try {
        setJobsLoading(true);
        setError(null);
        const jobResp = await api.listJobs(jobTypeFilter || undefined);
        if (!mounted) return;
        setJobs(jobResp);
      } catch (err) {
        if (mounted) {
          setError((err as Error).message);
        }
      } finally {
        if (mounted) {
          setJobsLoading(false);
        }
      }
    };
    loadJobs();
    return () => {
      mounted = false;
    };
  }, [jobTypeFilter]);

  const runningJobs = useMemo(
    () => jobs.filter((job) => job.status === "running").length,
    [jobs],
  );
  const keepAliveJobs = useMemo(
    () => jobs.filter((job) => job.job_type === "keep_alive").length,
    [jobs],
  );
  const monitorJobs = useMemo(
    () => jobs.filter((job) => job.job_type === "monitor").length,
    [jobs],
  );
  const scheduleJobs = useMemo(
    () => jobs.filter((job) => job.job_type === "schedule").length,
    [jobs],
  );

  // 获取默认查询的预设信息
  const dashboardTiles = dashboardPresets.map((entry) => {
    const matched = presets.find((preset) => preset.index === entry.index);
    return {
      index: entry.index,
      displayName: entry.label,
      venueName: matched?.venue_name ?? entry.label,
      fieldTypeName: matched?.field_type_name ?? entry.label,
    };
  });

  const showLoginNotice = !loginStatus || !loginStatus.users || loginStatus.users.length === 0;

  return (
    <>
      <div className="content-header">
        <div>
          <h2>我的运动日常</h2>
          <p className="content-subtitle">预订、监控、计划，在这里有序进行。</p>
        </div>
      </div>

      <section className="dashboard-hero" aria-labelledby="welcome-title">
        <div className="hero-copy">
          <span className="hero-eyebrow">YOUR NEXT GOOD MOVE</span>
          <h1 id="welcome-title">把时间留给<br /><span>热爱的运动。</span></h1>
          <p>找到合适的场地，安排喜欢的时段。<br />下一场尽兴，从这里开始。</p>
          <div className="hero-actions">
            <Link to="/slots" className="button button-primary">
              寻找运动场地 <span aria-hidden="true">↗</span>
            </Link>
            <Link to="/sessions" className="button hero-account-link">管理我的账号 <span aria-hidden="true">→</span></Link>
          </div>
          <div className="hero-service-status">
            <span className={`service-dot${health?.status === "ok" ? " is-connected" : ""}`} aria-hidden="true" />
            {health?.status === "ok" ? "预约服务已连接" : "正在连接预约服务"}
            {showLoginNotice ? <span>· 登录后查看实时场次</span> : null}
          </div>
        </div>
        <SportsIllustration className="hero-illustration" />
      </section>

      {error ? (
        <div className="panel notice notice-error">
          <strong>加载失败</strong>
          <span>{error}</span>
        </div>
      ) : null}

      <div className="status-grid">
        <StatusCard
          title="后台任务"
          value={jobsLoading ? "..." : jobs.length}
          meta={`${runningJobs} 个正在运行`}
        />
        <StatusCard
          title="会话保活"
          value={jobsLoading ? "..." : keepAliveJobs}
          meta="让账号保持在线"
        />
        <StatusCard
          title="监控任务"
          value={jobsLoading ? "..." : monitorJobs}
          meta="后台实时监控数量"
        />
        <StatusCard
          title="定时任务"
          value={jobsLoading ? "..." : scheduleJobs}
          meta="计划执行数"
        />
      </div>

      <section className="section">
        <h3>后台任务</h3>
        <div className="panel" style={{ gap: "16px" }}>
          <div className="filter-bar">
            <span className="muted-text" style={{ fontSize: "14px" }}>筛选任务类型：</span>
            <select
              value={jobTypeFilter}
              onChange={(event) => setJobTypeFilter(event.target.value)}
              className="input"
              style={{ maxWidth: "180px" }}
            >
              <option value="">全部类型</option>
              <option value="monitor">监控</option>
              <option value="schedule">定时</option>
              <option value="auto_booking">自动抢票</option>
              <option value="keep_alive">会话保活</option>
            </select>
          </div>
          {jobsLoading ? (
            <span className="muted-text">加载任务中…</span>
          ) : jobs.length === 0 ? (
            <div className="empty-state">
              <div className="empty-state-symbol" aria-hidden="true">
                <svg viewBox="0 0 64 64" fill="none">
                  <rect x="13" y="15" width="38" height="39" rx="9" fill="#E9E1FC" />
                  <path d="M23 11v10m18-10v10M21 31h22m-22 8h10" stroke="#2E2A5B" strokeWidth="2" strokeLinecap="round" />
                  <circle cx="44" cy="45" r="11" fill="#6EE7B7" />
                  <path d="m39 45 3 3 6-7" stroke="#2E2A5B" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>
              <div>
                <strong>把运动排进日常</strong>
                <p>还没有预约任务。创建一个计划，让运动按你的节奏进行。</p>
                <Link to="/schedule" className="text-button">安排第一个任务 <span aria-hidden="true">→</span></Link>
              </div>
            </div>
          ) : (
            <>
              <div className="table-container" style={{ overflowX: "auto" }}>
                <table className="table">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>名称</th>
                      <th>类型</th>
                      <th>状态</th>
                      <th>创建时间</th>
                      <th>最近启动</th>
                      <th>PID</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {jobs.map((job) => (
                      <tr key={job.job_id}>
                        <td>{job.job_id}</td>
                        <td>{job.name}</td>
                        <td>{jobTypeLabels[job.job_type] ?? job.job_type}</td>
                        <td>
                          <span
                            className={`chip ${
                              job.status === "running"
                                ? "chip-success"
                                : job.status === "pending"
                                  ? "chip-info"
                                  : "chip-warning"
                            }`}
                          >
                            {job.status}
                          </span>
                        </td>
                        <td>{job.created_at ? new Date(job.created_at).toLocaleString() : "-"}</td>
                        <td>{job.started_at ? new Date(job.started_at).toLocaleString() : "未启动"}</td>
                        <td>{job.pid ?? "-"}</td>
                        <td>
                          <JobDeleteButton job={job} onDeleted={() => window.location.reload()} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      </section>

      {/* 今日场次移动至页面底部 */}
      {loginStatus && loginStatus.users && loginStatus.users.length > 0 ? (
        <section className="section">
          <h3>📊 今日场次</h3>
          <div className="dashboard-preset-grid">
            {dashboardTiles.map((tile) => (
              <SlotTable
                key={tile.index}
                preset={tile.index}
                venueName={tile.venueName}
                fieldTypeName={tile.fieldTypeName}
                displayName={tile.displayName}
              />
            ))}
          </div>
        </section>
      ) : null}
    </>
  );
};

export default DashboardPage;
