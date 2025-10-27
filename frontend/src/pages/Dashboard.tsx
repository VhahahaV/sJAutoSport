import { useEffect, useMemo, useState } from "react";

import StatusCard from "../components/StatusCard";
import SlotTable from "../components/SlotTable";
import { api, type HealthResponse, type JobSummary, type Preset } from "../lib/api";

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
  const [loginStatus, setLoginStatus] = useState<any>(null);

  // 默认查询的预设 (气模体育中心羽毛球、学生中心健身房、子衿街健身房)
  const defaultPresets = [5, 3, 8];

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
  const defaultPresetInfos = presets.filter((p) => defaultPresets.includes(p.index));

  return (
    <>
      <div className="content-header">
        <div>
          <h2>控制台总览</h2>
          <p className="content-subtitle">快速了解系统运行状态与后台任务。</p>
        </div>
      </div>

      {/* 默认查询显示 */}
      {loginStatus && loginStatus.users && loginStatus.users.length > 0 && (
        <section className="section">
          <h3>📊 今日场次查询</h3>
          <div className="grid">
            {defaultPresetInfos.map((preset) => (
              <SlotTable
                key={preset.index}
                preset={preset.index}
                venueName={preset.venue_name}
                fieldTypeName={preset.field_type_name}
              />
            ))}
          </div>
        </section>
      )}
      
      {(!loginStatus || !loginStatus.users || loginStatus.users.length === 0) && (
        <div className="panel notice">
          <strong>⚠️ 未登录</strong>
          <span>请先登录后再查看场次信息。</span>
        </div>
      )}

      {error ? (
        <div className="panel notice notice-error">
          <strong>加载失败</strong>
          <span>{error}</span>
        </div>
      ) : null}

      <div className="grid">
        <StatusCard
          title="系统状态"
          value={health ? "在线" : "检查中"}
          meta={health ? "API 正常响应" : "等待 API 响应"}
        />
        <StatusCard
          title="后台任务"
          value={jobsLoading ? "..." : jobs.length}
          meta={`${runningJobs} 个正在运行`}
        />
        <StatusCard
          title="Keep-Alive 任务"
          value={jobsLoading ? "..." : keepAliveJobs}
          meta="用于保持 Cookie 有效"
        />
        <StatusCard
          title="监控任务"
          value={jobsLoading ? "..." : monitorJobs}
          meta="后台实时监控数量"
        />
        <StatusCard
          title="定时任务"
          value={jobsLoading ? "..." : scheduleJobs}
          meta="预设执行计划"
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
            <span className="muted-text">目前暂无任务。</span>
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
    </>
  );
};

export default DashboardPage;
