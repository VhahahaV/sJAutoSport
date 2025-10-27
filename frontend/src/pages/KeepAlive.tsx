import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  api,
  type KeepAliveJob,
  type KeepAliveSummary,
} from "../lib/api";

const KeepAlivePage = () => {
  const [jobs, setJobs] = useState<KeepAliveJob[]>([]);
  const [results, setResults] = useState<KeepAliveSummary[]>([]);
  const [loadingJobs, setLoadingJobs] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [formName, setFormName] = useState("KeepAlive");
  const [formInterval, setFormInterval] = useState(15);
  const [targetUser, setTargetUser] = useState("");

  const loadJobs = async () => {
    try {
      setLoadingJobs(true);
      const data = await api.listKeepAliveJobs();
      setJobs(data);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoadingJobs(false);
    }
  };

  useEffect(() => {
    void loadJobs();
  }, []);

  const handleRun = async (user?: string) => {
    try {
      setRunning(true);
      const requestPayload = { user: user || undefined };
      const data = await api.runKeepAlive(user);
      setResults(data);
      setError(null);
    } catch (err) {
      const message = (err as Error).message;
      setError(message);
    } finally {
      setRunning(false);
      void loadJobs();
    }
  };

  const handleCreateJob = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    try {
      setRunning(true);
      const payload = {
        name: formName || "KeepAlive",
        interval_minutes: Math.max(1, formInterval),
      };
      const response = await api.createKeepAliveJob(payload);
      setFormName("KeepAlive");
      setFormInterval(15);
      setError(null);
      await loadJobs();
    } catch (err) {
      const message = (err as Error).message;
      setError(message);
    } finally {
      setRunning(false);
    }
  };

  const handleDeleteJob = async (jobId: string) => {
    try {
      setRunning(true);
      await api.deleteKeepAliveJob(jobId);
      await loadJobs();
    } catch (err) {
      const message = (err as Error).message;
      setError(message);
    } finally {
      setRunning(false);
    }
  };

  const lastSuccessCount = useMemo(
    () => results.filter((item) => item.success).length,
    [results],
  );

  return (
    <>
      <div className="content-header">
        <div>
          <h2>会话保活</h2>
          <p style={{ color: "#667085", marginTop: "8px" }}>
            定时刷新所有账号，确保 Cookie 始终有效。
          </p>
        </div>
        <div className="panel-actions">
          <button
            className="button button-secondary"
            type="button"
            disabled={running}
            onClick={() => handleRun()}
          >
            刷新全部
          </button>
          <div style={{ display: "flex", gap: "8px" }}>
            <input
              placeholder="指定用户昵称或用户名"
              value={targetUser}
              onChange={(event) => setTargetUser(event.target.value)}
              style={{
                padding: "10px 14px",
                borderRadius: "10px",
                border: "1px solid rgba(148, 163, 184, 0.4)",
                fontSize: "14px",
              }}
            />
            <button
              className="button button-primary"
              type="button"
              disabled={running || !targetUser}
              onClick={() => handleRun(targetUser)}
            >
              刷新指定用户
            </button>
          </div>
        </div>
      </div>

      {error ? (
        <div className="panel" style={{ border: "1px solid #fca5a5" }}>
          <strong>操作失败</strong>
          <span style={{ color: "#b91c1c" }}>{error}</span>
        </div>
      ) : null}

      <section className="section">
        <h3>最近结果</h3>
        <div className="panel">
          {running && <span style={{ color: "#2563eb" }}>执行中…</span>}
          {!running && results.length === 0 ? (
            <span style={{ color: "#667085" }}>
              暂无记录，点击「刷新全部」开始第一次保活。
            </span>
          ) : null}
          {results.length > 0 ? (
            <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
              <div>
                成功{" "}
                <strong style={{ color: "#15803d" }}>{lastSuccessCount}</strong> /
                {results.length}
              </div>
              <table className="table">
                <thead>
                  <tr>
                    <th>昵称</th>
                    <th>用户名</th>
                    <th>状态</th>
                    <th>信息</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((result, index) => (
                    <tr key={`${result.username}-${index}`}>
                      <td>{result.nickname || "未命名"}</td>
                      <td>{result.username || "-"}</td>
                      <td>
                        <span
                          className={`chip ${
                            result.success ? "chip-success" : "chip-warning"
                          }`}
                        >
                          {result.success ? "成功" : "失败"}
                        </span>
                      </td>
                      <td>{result.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      </section>

      <section className="section">
        <h3>Keep-Alive 任务列表</h3>
        <div className="panel">
          {loadingJobs ? (
            <span style={{ color: "#667085" }}>加载中…</span>
          ) : jobs.length === 0 ? (
            <span style={{ color: "#667085" }}>暂无 Keep-Alive 任务。</span>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>名称</th>
                  <th>状态</th>
                  <th>间隔</th>
                  <th>创建时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => (
                  <tr key={job.job_id}>
                    <td>{job.name}</td>
                    <td>
                      <span
                        className={`chip ${
                          job.status === "running"
                            ? "chip-success"
                            : "chip-warning"
                        }`}
                      >
                        {job.status}
                      </span>
                    </td>
                    <td>{job.interval_minutes} 分钟</td>
                    <td>{new Date(job.created_at).toLocaleString()}</td>
                    <td>
                      <button
                        className="button button-secondary"
                        type="button"
                        onClick={() => handleDeleteJob(job.job_id)}
                        disabled={running}
                      >
                        删除
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>

      <section className="section">
        <h3>创建新的 Keep-Alive 任务</h3>
        <div className="panel">
          <form
            style={{ display: "flex", gap: "16px", flexWrap: "wrap" }}
            onSubmit={handleCreateJob}
          >
            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              <label htmlFor="job-name">任务名称</label>
              <input
                id="job-name"
                value={formName}
                onChange={(event) => setFormName(event.target.value)}
                required
                style={{
                  padding: "10px 14px",
                  borderRadius: "10px",
                  border: "1px solid rgba(148, 163, 184, 0.4)",
                  fontSize: "14px",
                }}
              />
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              <label htmlFor="job-interval">刷新间隔 (分钟)</label>
              <input
                id="job-interval"
                type="number"
                min={1}
                value={formInterval}
                onChange={(event) =>
                  setFormInterval(Number.parseInt(event.target.value, 10) || 15)
                }
                style={{
                  width: "120px",
                  padding: "10px 14px",
                  borderRadius: "10px",
                  border: "1px solid rgba(148, 163, 184, 0.4)",
                  fontSize: "14px",
                }}
              />
            </div>
            <div style={{ alignSelf: "flex-end" }}>
              <button
                className="button button-primary"
                type="submit"
                disabled={running}
              >
                创建任务
              </button>
            </div>
          </form>
        </div>
      </section>
    </>
  );
};

export default KeepAlivePage;
