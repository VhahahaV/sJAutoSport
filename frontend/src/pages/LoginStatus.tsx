import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import {
  api,
  type KeepAliveJob,
  type KeepAliveSummary,
  type LoginFlowResponse,
  type LoginStatusResponse,
  type UserInfoRecord,
  type UserSummary,
} from "../lib/api";

type PendingSession = {
  sessionId: string;
  username?: string | null;
  nickname?: string | null;
  captchaImage?: string | null;
  message?: string | null;
};

const toDataUrl = (image?: string | null, mime?: string | null) =>
  image ? `data:${mime ?? "image/png"};base64,${image}` : null;

const sexLabel = (value?: string | null) => {
  if (value === "0") return "男";
  if (value === "1") return "女";
  return value ?? "未知";
};

const LoginStatusPage = () => {
  const [status, setStatus] = useState<LoginStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [statusError, setStatusError] = useState<string | null>(null);

  const [form, setForm] = useState({ username: "", password: "", nickname: "" });
  const [loginBusy, setLoginBusy] = useState(false);
  const [verifyBusy, setVerifyBusy] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);
  const [loginInfo, setLoginInfo] = useState<string | null>(null);
  const [pendingSession, setPendingSession] = useState<PendingSession | null>(null);
  const [captchaCode, setCaptchaCode] = useState("");
  const [knownUsers, setKnownUsers] = useState<UserSummary[]>([]);
  const [usersError, setUsersError] = useState<string | null>(null);
  const [usersLoading, setUsersLoading] = useState(false);
  const [userRecords, setUserRecords] = useState<UserInfoRecord[]>([]);
  const [userInfoLoading, setUserInfoLoading] = useState(false);
  const [userInfoError, setUserInfoError] = useState<string | null>(null);
  const [keepAliveJobs, setKeepAliveJobs] = useState<KeepAliveJob[]>([]);
  const [keepAliveResults, setKeepAliveResults] = useState<KeepAliveSummary[]>([]);
  const [keepAliveLoading, setKeepAliveLoading] = useState(false);
  const [keepAliveError, setKeepAliveError] = useState<string | null>(null);
  const [keepAliveTarget, setKeepAliveTarget] = useState("");
  const [jobName, setJobName] = useState("KeepAlive");
  const [jobInterval, setJobInterval] = useState(15);

  const loadStatus = useCallback(async () => {
    setLoading(true);
    setStatusError(null);
    try {
      const result = await api.getLoginStatus();
      setStatus(result);
    } catch (err) {
      setStatusError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadUsers = useCallback(async () => {
    setUsersLoading(true);
    setUsersError(null);
    try {
      const result = await api.listUsers();
      const items = result.users ?? [];
      setKnownUsers(items);
      setForm((prev) => {
        if (prev.username || !items.length) {
          return prev;
        }
        const candidate =
          items.find((user) => user.is_active && user.username) ??
          items.find((user) => user.username);
        if (!candidate || !candidate.username) {
          return prev;
        }
        return {
          ...prev,
          username: candidate.username,
          nickname: candidate.nickname ?? prev.nickname,
          password: candidate.password_masked ?? prev.password,
        };
      });
    } catch (err) {
      setUsersError((err as Error).message);
    } finally {
      setUsersLoading(false);
    }
  }, []);

  const loadUserInfo = useCallback(async () => {
    try {
      setUserInfoLoading(true);
      setUserInfoError(null);
      const response = await api.getUserInfos();
      setUserRecords(response.users ?? []);
    } catch (err) {
      setUserInfoError((err as Error).message);
      setUserRecords([]);
    } finally {
      setUserInfoLoading(false);
    }
  }, []);

  const loadKeepAliveJobs = useCallback(async () => {
    try {
      setKeepAliveLoading(true);
      setKeepAliveError(null);
      const data = await api.listKeepAliveJobs();
      setKeepAliveJobs(data);
    } catch (err) {
      setKeepAliveError((err as Error).message);
    } finally {
      setKeepAliveLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  useEffect(() => {
    void loadUsers();
  }, [loadUsers]);

  useEffect(() => {
    void loadUserInfo();
    void loadKeepAliveJobs();
  }, [loadUserInfo, loadKeepAliveJobs]);

  const handleLoginResponse = async (result: LoginFlowResponse) => {
    if (!result.success) {
      setPendingSession(null);
      setLoginError(result.message ?? "登录失败");
      return;
    }

    if (result.captcha_required) {
      if (!result.session_id) {
        setLoginError("登录会话创建失败，缺少 session_id");
        setPendingSession(null);
        return;
      }
      setPendingSession({
        sessionId: result.session_id,
        username: result.username,
        nickname: result.nickname,
        captchaImage: toDataUrl(result.captcha_image, result.captcha_mime),
        message: result.message ?? "验证码已生成，请在 5 分钟内输入。",
      });
      setLoginInfo(result.message ?? "验证码已生成，请输入验证码完成登录。");
      setCaptchaCode("");
      return;
    }

    setPendingSession(null);
    setCaptchaCode("");
    setLoginInfo(result.message ?? "登录成功");
    setForm({ username: "", password: "", nickname: "" });
    await Promise.all([loadStatus(), loadUsers(), loadUserInfo(), loadKeepAliveJobs()]);
  };

  const handleStartLogin = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (loginBusy) return;
    setLoginError(null);
    setLoginInfo(null);
    setLoginBusy(true);

    try {
      const payload: Record<string, string> = {};
      const username = form.username.trim();
      const nickname = form.nickname.trim();
      if (username) payload.username = username;
      if (form.password) payload.password = form.password;
      if (nickname) payload.nickname = nickname;

      const result = await api.startLogin(payload);
      await handleLoginResponse(result);
    } catch (err) {
      setLoginError((err as Error).message);
    } finally {
      setLoginBusy(false);
    }
  };

  const handleSubmitCaptcha = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!pendingSession || verifyBusy) return;

    const code = captchaCode.trim();
    if (!code) {
      setLoginError("请输入验证码");
      return;
    }

    setVerifyBusy(true);
    setLoginError(null);
    setLoginInfo(null);

    try {
      const result = await api.submitLoginCode({
        session_id: pendingSession.sessionId,
        code,
      });

      if (result.success) {
        await handleLoginResponse(result);
        return;
      }

      if (result.retry) {
        setLoginInfo(result.message ?? "验证码错误，请重试。");
        setCaptchaCode("");
        setPendingSession({
          sessionId: pendingSession.sessionId,
          username: result.username ?? pendingSession.username,
          nickname: result.nickname ?? pendingSession.nickname,
          captchaImage: toDataUrl(
            result.captcha_image ?? undefined,
            result.captcha_mime ?? undefined,
          ),
          message: result.message ?? pendingSession.message,
        });
        return;
      }

      setPendingSession(null);
      setCaptchaCode("");
      setLoginError(result.message ?? "登录失败");
    } catch (err) {
      setLoginError((err as Error).message);
    } finally {
      setVerifyBusy(false);
    }
  };

  const handleCancelSession = async () => {
    if (!pendingSession) return;
    setVerifyBusy(true);
    setLoginError(null);
    setLoginInfo(null);
    try {
      const result = await api.cancelLoginSession(pendingSession.sessionId);
      if (result.success) {
        setLoginInfo(result.message ?? "登录流程已取消");
      } else {
        setLoginError(result.message ?? "取消登录流程失败");
      }
    } catch (err) {
      setLoginError((err as Error).message);
    } finally {
      setVerifyBusy(false);
      setPendingSession(null);
      setCaptchaCode("");
    }
  };

  const handleRunKeepAlive = async (user?: string) => {
    try {
      setKeepAliveLoading(true);
      const data = await api.runKeepAlive(user);
      setKeepAliveResults(data);
      setKeepAliveError(null);
    } catch (err) {
      const message = (err as Error).message;
      setKeepAliveError(message);
    } finally {
      setKeepAliveLoading(false);
      void loadKeepAliveJobs();
      void loadStatus();
      void loadUserInfo();
    }
  };

  const handleCreateKeepAliveJob = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    try {
      setKeepAliveLoading(true);
      const payload = {
        name: jobName || "KeepAlive",
        interval_minutes: Math.max(1, jobInterval),
      };
      const response = await api.createKeepAliveJob(payload);
      setJobName("KeepAlive");
      setJobInterval(15);
      setKeepAliveError(null);
      await loadKeepAliveJobs();
    } catch (err) {
      const message = (err as Error).message;
      setKeepAliveError(message);
    } finally {
      setKeepAliveLoading(false);
    }
  };

  const handleDeleteKeepAliveJob = async (jobId: string) => {
    try {
      setKeepAliveLoading(true);
      await api.deleteKeepAliveJob(jobId);
      await loadKeepAliveJobs();
    } catch (err) {
      const message = (err as Error).message;
      setKeepAliveError(message);
    } finally {
      setKeepAliveLoading(false);
    }
  };

  const keepAliveSuccessCount = useMemo(
    () => keepAliveResults.filter((item) => item.success).length,
    [keepAliveResults],
  );

  return (
    <>
      <div className="content-header">
        <div>
          <h2>用户会话与保活</h2>
          <p style={{ color: "#667085", marginTop: "8px" }}>
            在此发起登录流程、查看用户档案并统一维护会话保活。
          </p>
        </div>
        <button
          className="button button-secondary"
          type="button"
          onClick={() => {
            void loadStatus();
            void loadUsers();
            void loadUserInfo();
            void loadKeepAliveJobs();
          }}
          disabled={loading}
        >
          {loading ? "刷新中…" : "刷新全部"}
        </button>
      </div>

      <div className="panel">
        <div className="section">
          <h3>发起登录</h3>
          <p style={{ color: "#667085", margin: 0 }}>
            提供用户名与密码后即可开始登录。如配置文件已保存凭据，可留空以复用。
          </p>
        </div>

        <div className="user-quick-select">
          <div className="user-quick-header">
            <span>已配置用户</span>
            <button
              className="text-button"
              type="button"
              onClick={() => void loadUsers()}
              disabled={usersLoading}
            >
              {usersLoading ? "刷新中…" : "刷新列表"}
            </button>
          </div>
          {usersError ? (
            <div className="notice notice-error">{usersError}</div>
          ) : null}
          {knownUsers.length ? (
            <div className="user-chip-group">
              {knownUsers.map((user, index) => {
                const username = user.username ?? "";
                const nickname = user.nickname ?? "";
                const isSelected =
                  username && form.username && username.toLowerCase() === form.username.toLowerCase();
                return (
                  <button
                    key={`${username || "user"}-${index}`}
                    type="button"
                    className={`user-chip${isSelected ? " active" : ""}${
                      user.is_active ? " current" : ""
                    }`}
                    onClick={() =>
                      setForm({
                        username,
                        password: user.password_masked || "",
                        nickname: nickname || deriveNickname(username),
                      })
                    }
                  >
                    <span className="user-chip-name">{nickname || username || "未命名用户"}</span>
                    <span className="user-chip-meta">
                      {username || "（未配置用户名）"}
                      {user.is_active ? " · 当前" : ""}
                    </span>
                  </button>
                );
              })}
            </div>
          ) : (
            <span className="muted-text">暂无用户配置，请在 config.py 的 AUTH 中填写。</span>
          )}
        </div>

        <form onSubmit={handleStartLogin} className="form-grid">
          <div className="form-field">
            <label htmlFor="login-username">用户名</label>
            <input
              id="login-username"
              className="input"
              placeholder="学号 / 邮箱 / 配置文件中的用户名"
              value={form.username}
              onChange={(event) => {
                const value = event.target.value;
                setForm((prev) => ({
                  ...prev,
                  username: value,
                  nickname: prev.nickname ? prev.nickname : deriveNickname(value),
                }));
              }}
              autoComplete="username"
            />
          </div>
          <div className="form-field">
            <label htmlFor="login-password">密码</label>
            <input
              id="login-password"
              className="input"
              type="password"
              placeholder="登录密码"
              value={form.password}
              onChange={(event) => setForm((prev) => ({ ...prev, password: event.target.value }))}
              autoComplete="current-password"
            />
          </div>
          <div className="form-field">
            <label htmlFor="login-nickname">昵称（可选）</label>
            <input
              id="login-nickname"
              className="input"
              placeholder="用于标识此账号"
              value={form.nickname}
              onChange={(event) => setForm((prev) => ({ ...prev, nickname: event.target.value }))}
            />
          </div>
          <div className="panel-actions" style={{ alignItems: "flex-end" }}>
            <button
              className="button button-primary"
              type="submit"
              disabled={loginBusy || verifyBusy}
            >
              {loginBusy ? "处理中…" : "开始登录"}
            </button>
            {pendingSession ? (
              <button
                className="button button-secondary"
                type="button"
                onClick={handleCancelSession}
                disabled={verifyBusy}
              >
                取消登录
              </button>
            ) : null}
          </div>
        </form>

        {pendingSession ? (
          <form onSubmit={handleSubmitCaptcha} className="form-grid">
            <div className="form-field">
              <label htmlFor="captcha-code">验证码</label>
              <input
                id="captcha-code"
                className="input"
                value={captchaCode}
                onChange={(event) => setCaptchaCode(event.target.value)}
                placeholder="请输入验证码"
                autoComplete="one-time-code"
              />
            </div>
            {pendingSession.captchaImage ? (
              <div className="form-field" style={{ alignItems: "flex-start" }}>
                <label style={{ visibility: "hidden" }}>验证码图片</label>
                <img
                  src={pendingSession.captchaImage}
                  alt="验证码"
                  className="captcha-image"
                />
              </div>
            ) : null}
            <div className="panel-actions" style={{ alignItems: "flex-end" }}>
              <button
                className="button button-primary"
                type="submit"
                disabled={verifyBusy}
              >
                {verifyBusy ? "提交中…" : "提交验证码"}
              </button>
            </div>
          </form>
        ) : null}

        {loginInfo ? <div className="notice notice-success">{loginInfo}</div> : null}
        {loginError ? <div className="notice notice-error">{loginError}</div> : null}
      </div>

      {statusError ? (
        <div className="panel" style={{ border: "1px solid #fca5a5" }}>
          <strong>状态获取失败</strong>
          <span style={{ color: "#b91c1c" }}>{statusError}</span>
        </div>
      ) : null}

      <div className="panel">
        <div className="section" style={{ marginBottom: "-8px" }}>
          <h3>登录状态</h3>
        </div>
        {loading ? (
          <span style={{ color: "#667085" }}>加载中…</span>
        ) : knownUsers.length || (status && status.success) ? (
          <table className="table">
            <thead>
              <tr>
                <th>昵称</th>
                <th>用户名</th>
                <th>有效期</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              {(knownUsers.length ? knownUsers : status?.users || []).map((user, index) => (
                <tr key={user.key || `${user.username || "user"}-${index}`}>
                  <td>{user.nickname || "未命名"}</td>
                  <td>{user.username || "-"}</td>
                  <td>
                    {user.expires_at
                      ? new Date(user.expires_at).toLocaleString()
                      : "未知"}
                  </td>
                  <td>
                    {user.is_active ? (
                      <span className="chip chip-success">当前使用</span>
                    ) : (
                      <span className="chip chip-info">备用</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <span style={{ color: "#667085" }}>
            尚未保存任何登录凭据，一旦完成登录这里会显示结果。
          </span>
        )}
      </div>

      <section className="section">
        <div className="content-header" style={{ padding: 0 }}>
          <div>
            <h3>用户信息</h3>
            <p style={{ color: "#667085", marginTop: "4px" }}>
              查询当前 Cookie 绑定的用户档案（来源于校园系统接口）。
            </p>
          </div>
          <button
            className="button button-secondary"
            type="button"
            onClick={() => void loadUserInfo()}
            disabled={userInfoLoading}
          >
            {userInfoLoading ? "刷新中…" : "重新获取"}
          </button>
        </div>
        <div className="panel">
          {userInfoError ? (
            <div className="notice notice-error">{userInfoError}</div>
          ) : null}
          {userInfoLoading ? (
            <span style={{ color: "#667085" }}>加载中…</span>
          ) : userRecords.length === 0 ? (
            <span style={{ color: "#667085" }}>暂无用户信息，请先完成登录。</span>
          ) : (
            userRecords.map((record, index) => {
              const profile = record.profile || {};
              return (
                <div
                  key={`${record.username || record.nickname || index}`}
                  style={{
                    border: "1px solid rgba(148, 163, 184, 0.25)",
                    borderRadius: "12px",
                    padding: "16px",
                    marginBottom: "12px",
                    display: "grid",
                    gap: "10px",
                    gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
                  }}
                >
                  <div>
                    <strong>昵称：</strong>
                    {record.nickname || "未命名"}
                  </div>
                  <div>
                    <strong>用户名：</strong>
                    {record.username || "-"}
                  </div>
                  <div>
                    <strong>状态：</strong>
                    <span className={`chip ${record.success ? "chip-success" : "chip-warning"}`}>
                      {record.success ? "有效" : "失效"}
                    </span>
                    {record.is_active ? (
                      <span style={{ marginLeft: "6px", color: "#2563eb" }}>当前活跃</span>
                    ) : null}
                  </div>
                  <div>
                    <strong>姓名：</strong>
                    {profile.user_name || "-"}
                  </div>
                  <div>
                    <strong>登录名：</strong>
                    {profile.login_name || "-"}
                  </div>
                  <div>
                    <strong>手机号：</strong>
                    {profile.phone || "-"}
                  </div>
                  <div>
                    <strong>性别：</strong>
                    {sexLabel(profile.sex)}
                  </div>
                  <div>
                    <strong>部门：</strong>
                    {profile.dept || "-"}
                  </div>
                  <div>
                    <strong>学号：</strong>
                    {profile.code || "-"}
                  </div>
                  <div>
                    <strong>班级：</strong>
                    {profile.class_no || "-"}
                  </div>
                  <div>
                    <strong>管理员：</strong>
                    {profile.admin ? "是" : "否"}
                  </div>
                  <div style={{ gridColumn: "1 / -1" }}>
                    <strong>角色：</strong>
                    {profile.roles && profile.roles.length > 0 ? profile.roles.join(" / ") : "无"}
                  </div>
                  {!record.success && record.message ? (
                    <div style={{ gridColumn: "1 / -1", color: "#b91c1c" }}>
                      错误：{record.message}
                    </div>
                  ) : null}
                </div>
              );
            })
          )}
        </div>
      </section>

      <section className="section">
        <div className="content-header" style={{ padding: 0 }}>
          <div>
            <h3>会话保活</h3>
            <p style={{ color: "#667085", marginTop: "4px" }}>
              定时刷新 Cookie，确保账号随时可用。
            </p>
          </div>
          <div className="panel-actions" style={{ padding: 0 }}>
            <button
              className="button button-secondary"
              type="button"
              disabled={keepAliveLoading}
              onClick={() => handleRunKeepAlive()}
            >
              刷新全部
            </button>
            <div style={{ display: "flex", gap: "8px" }}>
              <input
                placeholder="指定用户昵称或用户名"
                value={keepAliveTarget}
                onChange={(event) => setKeepAliveTarget(event.target.value)}
                className="input"
                style={{ minWidth: "220px" }}
              />
              <button
                className="button button-primary"
                type="button"
                disabled={keepAliveLoading || !keepAliveTarget}
                onClick={() => handleRunKeepAlive(keepAliveTarget)}
              >
                刷新指定用户
              </button>
            </div>
          </div>
        </div>

        {keepAliveError ? <div className="notice notice-error">{keepAliveError}</div> : null}

        <div className="panel">
          {keepAliveLoading && <span style={{ color: "#2563eb" }}>执行中…</span>}
          {!keepAliveLoading && keepAliveResults.length === 0 ? (
            <span style={{ color: "#667085" }}>暂无保活记录，点击「刷新全部」开始。</span>
          ) : null}

          {keepAliveResults.length > 0 ? (
            <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
              <div>
                成功 <strong style={{ color: "#15803d" }}>{keepAliveSuccessCount}</strong> /
                {keepAliveResults.length}
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
                  {keepAliveResults.map((result, index) => (
                    <tr key={`${result.username}-${index}`}>
                      <td>{result.nickname || "未命名"}</td>
                      <td>{result.username || "-"}</td>
                      <td>
                        <span className={`chip ${result.success ? "chip-success" : "chip-warning"}`}>
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

        <div className="panel">
          <h4 style={{ margin: 0 }}>定时保活任务</h4>
          <form onSubmit={handleCreateKeepAliveJob} className="form-grid">
            <div className="form-field">
              <label htmlFor="keepalive-name">任务名称</label>
              <input
                id="keepalive-name"
                className="input"
                value={jobName}
                onChange={(event) => setJobName(event.target.value)}
              />
            </div>
            <div className="form-field">
              <label htmlFor="keepalive-interval">间隔（分钟）</label>
              <input
                id="keepalive-interval"
                className="input"
                type="number"
                min={1}
                value={jobInterval}
                onChange={(event) => setJobInterval(Number(event.target.value) || 1)}
              />
            </div>
            <div className="panel-actions" style={{ alignItems: "flex-end" }}>
              <button
                className="button button-primary"
                type="submit"
                disabled={keepAliveLoading}
              >
                创建任务
              </button>
            </div>
          </form>

          {keepAliveLoading && keepAliveJobs.length === 0 ? (
            <span style={{ color: "#667085" }}>加载任务中…</span>
          ) : keepAliveJobs.length === 0 ? (
            <span style={{ color: "#667085" }}>暂无保活任务。</span>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>名称</th>
                  <th>状态</th>
                  <th>间隔</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {keepAliveJobs.map((job) => (
                  <tr key={job.job_id}>
                    <td>{job.job_id}</td>
                    <td>{job.name}</td>
                    <td>{job.status}</td>
                    <td>{job.interval_minutes} 分钟</td>
                    <td>
                      <button
                        className="text-button"
                        type="button"
                        onClick={() => void handleDeleteKeepAliveJob(job.job_id)}
                        disabled={keepAliveLoading}
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
    </>
  );
};

export default LoginStatusPage;
