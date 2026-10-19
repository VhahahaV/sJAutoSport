import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, type KeepAliveSettings, type UserProfile } from "../lib/api";

export default function KeepAlivePage() {
  const [settings, setSettings] = useState<KeepAliveSettings>({ enabled: false, interval_minutes: 15 });
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(true);
  const [profileError, setProfileError] = useState("");
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const loadProfile = useCallback(async () => {
    setProfileLoading(true); setProfileError("");
    try {
      const result = await api.getAccountInfo();
      if (!result.success || !result.profile) throw new Error(result.message || "未获得用户资料，请重试");
      setProfile(result.profile);
    } catch (error) { setProfileError((error as Error).message); }
    finally { setProfileLoading(false); }
  }, []);
  useEffect(() => {
    void loadProfile();
    api.getKeepAlive().then(settings => { setSettings(settings); setReady(true); }).catch(error => setError(error.message));
  }, [loadProfile]);
  async function save(event: FormEvent) {
    event.preventDefault(); setBusy(true); setMessage(""); setError("");
    try { setSettings(await api.configureKeepAlive({ enabled: settings.enabled, interval_minutes: settings.interval_minutes })); setMessage("会话保活设置已保存。"); }
    catch (error) { setError((error as Error).message); } finally { setBusy(false); }
  }
  async function refresh() {
    setBusy(true); setMessage(""); setError("");
    try { const result = await api.runKeepAlive(); if (result.success) { setMessage(result.message); await loadProfile(); } else setError(result.message); setSettings(await api.getKeepAlive()); }
    catch (error) { setError((error as Error).message); } finally { setBusy(false); }
  }
  async function logout() {
    if (!window.confirm("退出后会暂停正在运行的监控并关闭自动保活，确认退出？")) return;
    setBusy(true); setError("");
    try { await api.logout(); window.dispatchEvent(new Event("session-expired")); }
    catch (error) { setError((error as Error).message); } finally { setBusy(false); }
  }
  return <>
    <div className="content-header"><div><h2>账号与会话</h2><p className="content-subtitle">管理当前登录账号，以及后台运行时的会话维护。</p></div></div>
    {error && <p className="notice notice-error" role="alert">{error}</p>}
    {message && <p className="notice notice-success" role="status">{message}</p>}
    <section className="panel" aria-busy={profileLoading} aria-label="当前账号资料">
      <div className="content-header">
        <h3>当前账号</h3>
        <div className="panel-actions">
          <button className="button button-secondary" disabled={profileLoading || busy} onClick={loadProfile}>{profileLoading ? "正在读取…" : "刷新资料"}</button>
          <button className="button button-danger" disabled={busy} onClick={logout}>退出登录</button>
        </div>
      </div>
      {profileError && <p className="notice notice-error" role="alert">资料读取失败：{profileError}。可以点击“刷新资料”重试。</p>}
      {profile ? <>
        <div className="account-identity">
          <span className="account-avatar" aria-hidden="true">{(profile.user_name || profile.login_name || "").slice(0, 1)}</span>
          <div><h4>{profile.user_name || profile.login_name}</h4><p className="muted-text">交大体育预约平台 · 当前登录用户</p></div>
        </div>
        <dl className="account-details">
          <div><dt>姓名</dt><dd>{profile.user_name || "未提供"}</dd></div>
          <div><dt>jAccount 账号</dt><dd>{profile.login_name || "未提供"}</dd></div>
          <div><dt>学工号</dt><dd>{profile.code || "未提供"}</dd></div>
          <div><dt>院系 / 部门</dt><dd>{profile.dept || "未提供"}</dd></div>
          <div><dt>班级</dt><dd>{profile.class_no || "未提供"}</dd></div>
          <div><dt>用户角色</dt><dd>{profile.roles?.length ? profile.roles.join("、") : "未提供"}</dd></div>
        </dl>
      </> : !profileError && <p className="muted-text" role="status">正在从体育预约平台读取个人资料…</p>}
    </section>
    <section className="panel"><h3>会话维护与自动恢复</h3><p className="muted-text">定期检查运动站登录。过期时尝试用已保存的 jAccount 会话重新授权，成功后继续监控；jAccount 也失效时需要重新扫码或填写验证码。服务器上的 core 需保持运行。</p>
      <dl className="account-details">
        <div><dt>jAccount 自动恢复</dt><dd>{!ready ? "正在读取…" : settings.session?.sso_available ? "已保存 SSO 会话，可在过期时尝试恢复" : settings.session?.login_required ? "需要重新登录" : "未保存 SSO 会话，请重新登录一次"}</dd></div>
        <div><dt>最近验证有效</dt><dd>{settings.session?.verified_at ? new Date(settings.session.verified_at).toLocaleString() : "暂无记录"}</dd></div>
        <div><dt>最近自动恢复</dt><dd>{settings.session?.renewed_at ? new Date(settings.session.renewed_at).toLocaleString() : "暂无恢复记录"}</dd></div>
        <div><dt>服务器有效期</dt><dd>由校园服务器决定，无法预先确定</dd></div>
      </dl>
      <form className="form-grid" onSubmit={save}>
        <label className="field"><span>后台会话维护</span><input type="checkbox" disabled={busy || !ready} checked={settings.enabled} onChange={e => setSettings({ ...settings, enabled: e.target.checked })} /></label>
        <label className="field">检查间隔（分钟）<input type="number" min={1} disabled={busy || !ready || !settings.enabled} value={settings.interval_minutes} onChange={e => setSettings({ ...settings, interval_minutes: Number(e.target.value) })} required /></label>
        <div className="form-actions"><button className="button button-primary" disabled={busy || !ready}>{busy ? "处理中…" : "保存设置"}</button><button className="button button-secondary" type="button" onClick={refresh} disabled={busy || !ready}>立即检查会话</button></div>
      </form>
      <p className="muted-text">最近检查：{settings.last_run ? `${new Date(settings.last_run).toLocaleString()} · ${settings.last_result?.message || ""}` : "暂无检查记录"}</p>
    </section>
  </>;
}
