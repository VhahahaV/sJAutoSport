import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type LoginFlowResponse, type QrLogin } from "../lib/api";
import SportsIllustration from "../components/SportsIllustration";

type Props = { onRefresh: () => Promise<void> };
const waiting = (qr: QrLogin | null) => qr && ["connecting", "waiting", "confirming"].includes(qr.status);

export default function LoginStatusPage({ onRefresh }: Props) {
  const navigate = useNavigate();
  const [mode, setMode] = useState<"qr" | "password">("qr");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [pending, setPending] = useState<LoginFlowResponse | null>(null);
  const [code, setCode] = useState("");
  const [qr, setQr] = useState<QrLogin | null>(null);
  const [busy, setBusy] = useState(false);
  const [qrBusy, setQrBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const started = useRef(false);
  const qrSession = useRef<string | null>(null);
  const polling = useRef(false);

  const generateQr = useCallback(async () => {
    setQrBusy(true); setError(""); setQr(null);
    try { const result = await api.startQrLogin(); qrSession.current = result.session_id || null; setQr(result); }
    catch (error) { setError((error as Error).message); }
    finally { setQrBusy(false); }
  }, []);

  useEffect(() => {
    if (mode === "qr" && !started.current) { started.current = true; void generateQr(); }
  }, [mode, generateQr]);

  useEffect(() => {
    if (mode !== "qr" || !qr?.session_id || !waiting(qr)) return;
    let active = true;
    const session = qr.session_id;
    const timer = window.setInterval(async () => {
      if (polling.current) return;
      polling.current = true;
      try {
        const result = await api.getQrLogin(session);
        if (!active) return;
        setQr(result);
        if (result.status === "success") { qrSession.current = null; await onRefresh(); navigate("/dashboard"); }
      } catch (error) { if (active) { setError((error as Error).message); setQr(previous => previous ? { ...previous, status: "error" } : null); } }
      finally { polling.current = false; }
    }, 1500);
    return () => { active = false; window.clearInterval(timer); };
  }, [mode, qr?.session_id, qr?.status, onRefresh, navigate]);

  async function changeMode(next: "qr" | "password") {
    if (next === mode || busy || qrBusy) return;
    setError(""); setMessage("");
    try {
      if (qrSession.current) { await api.cancelQrLogin(qrSession.current); qrSession.current = null; }
      if (pending?.session_id) await api.cancelLoginSession(pending.session_id);
    } catch (error) { setError((error as Error).message); }
    setPending(null); setCode(""); setQr(null); setMode(next);
    if (next === "qr") { started.current = true; await generateQr(); }
  }

  async function accept(result: LoginFlowResponse) {
    setPassword(""); setCode(""); setMessage(result.message || "");
    if (result.captcha_base64 && result.session_id) { setPending(result); return; }
    setPending(null);
    if (result.success) { await onRefresh(); navigate("/dashboard"); }
    else setError(result.message || "登录未完成，请重试");
  }
  async function login(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try { await accept(await api.startLogin({ username: username.trim(), password })); }
    catch (error) { setError((error as Error).message); } finally { setBusy(false); }
  }
  async function verify(event: FormEvent) {
    event.preventDefault(); if (!pending?.session_id) return;
    setBusy(true); setError("");
    try { await accept(await api.submitLoginCode({ session_id: pending.session_id, code: code.trim() })); }
    catch (error) { setError((error as Error).message); } finally { setBusy(false); }
  }
  async function restartPassword() {
    if (pending?.session_id) await api.cancelLoginSession(pending.session_id);
    setPending(null); setCode(""); setMessage(""); setError("");
  }

  return <main className="signin-shell">
    <header className="signin-header"><Link to="/" className="signin-brand"><img src="/favicon.svg" alt="" width={38} height={38} /><span>SJTU <strong>SPORTS</strong><small>交大运动空间</small></span></Link><a href="https://sports.sjtu.edu.cn/" target="_blank" rel="noreferrer" className="signin-official">体育预约平台 <span aria-hidden="true">↗</span></a></header>
    <div className="signin-layout">
      <section className="signin-story" aria-labelledby="signin-heading">
        <span className="signin-eyebrow"><span aria-hidden="true" /> MAKE ROOM FOR PLAY</span>
        <h1 id="signin-heading">生活很满，<br />也要留点时间<br /><span>给热爱的运动。</span></h1>
        <p className="signin-intro">好场地，好时光。<br />登录你的交大账号，下一场尽兴从这里开始。</p>
        <SportsIllustration className="signin-illustration" />
        <div className="signin-story-note"><span className="signin-note-icon" aria-hidden="true">✦</span><span>少一点安排，多一点热爱。<br /><strong>让运动，轻松发生。</strong></span></div>
      </section>
      <section className="signin-card" aria-label="登录交大运动空间">
        <span className="signin-card-kicker">YOUR NEXT GOOD MOVE</span>
        <h2>欢迎来到运动空间</h2>
        <p className="signin-card-subtitle">使用 jAccount 登录，开启今天的好状态。</p>
          <div className="signin-tabs" role="tablist" aria-label="登录方式"><button type="button" role="tab" aria-selected={mode === "qr"} aria-controls="signin-qr" className={mode === "qr" ? "is-active" : ""} onClick={() => changeMode("qr")} disabled={busy || qrBusy}>扫码登录 <span className="signin-recommended">推荐</span></button><button type="button" role="tab" aria-selected={mode === "password"} aria-controls="signin-password" className={mode === "password" ? "is-active" : ""} onClick={() => changeMode("password")} disabled={busy || qrBusy}>密码登录</button></div>
          {mode === "qr" ? <div id="signin-qr" role="tabpanel" className="signin-qr-panel">
            <div className={`signin-qr-frame${qr?.status === "confirming" ? " is-confirming" : ""}`}>
              {qr?.qr_base64 && waiting(qr) ? <img src={`data:${qr.qr_mime || "image/png"};base64,${qr.qr_base64}`} alt="jAccount 登录二维码，请使用交我办或微信扫描" width={216} height={216} /> : <div className="signin-qr-placeholder">{qrBusy ? <><span className="signin-spinner" aria-hidden="true" /><span>正在准备二维码</span></> : <><svg viewBox="0 0 64 64" fill="none" aria-hidden="true"><path d="M7 7h18v18H7zM39 7h18v18H39zM7 39h18v18H7zM39 39h7v7h-7zM50 39h7v18H39v-7" stroke="currentColor" strokeWidth="4" strokeLinejoin="round" /></svg><span>{qr?.status === "expired" ? "二维码已过期" : "重新准备，马上出发"}</span></>}</div>}
              {qr?.status === "confirming" && <div className="signin-qr-confirm"><span className="signin-spinner" aria-hidden="true" /> 正在确认登录</div>}
            </div>
            <p className="signin-scan-tip">打开 <strong>交我办</strong> 或 <strong>微信</strong> 扫一扫</p>
            <p className="signin-qr-status" role="status">{qr?.message || "在手机上确认，即可安全登录"}</p>
            <button className="signin-text-button" type="button" onClick={generateQr} disabled={qrBusy}>{qrBusy ? "正在生成…" : "↻ 刷新二维码"}</button>
          </div> : <div id="signin-password" role="tabpanel">
            {pending ? <form className="signin-form" onSubmit={verify}><p className="signin-captcha-caption">再确认一下，是你本人。</p><div className="signin-captcha-preview"><img src={`data:${pending.captcha_mime || "image/jpeg"};base64,${pending.captcha_base64}`} alt="登录验证码" /><span>请输入左侧图片中的字符</span></div><label className="signin-field">验证码<input autoFocus autoComplete="off" placeholder="填写图片中的验证码" value={code} onChange={e => setCode(e.target.value)} required /></label><button className="button button-primary signin-submit" disabled={busy}>{busy ? "正在验证…" : "验证并登录 →"}</button><button className="signin-text-button" type="button" onClick={() => restartPassword().catch(error => setError(error.message))} disabled={busy}>返回账号密码</button></form> : <form className="signin-form" onSubmit={login}>
              <label className="signin-field">jAccount 账号<div className="signin-input-wrap"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4" /><path d="M4 22v-3a8 8 0 0 1 16 0v3" /></svg><input autoComplete="username" placeholder="用户名 / 交大邮箱" value={username} onChange={e => setUsername(e.target.value)} required /></div></label>
              <label className="signin-field">密码<div className="signin-input-wrap"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="10" width="16" height="12" rx="3" /><path d="M8 10V6a4 4 0 0 1 8 0v4M12 15v3" /></svg><input type={showPassword ? "text" : "password"} autoComplete="current-password" placeholder="请输入 jAccount 密码" value={password} onChange={e => setPassword(e.target.value)} required /><button type="button" aria-label={showPassword ? "隐藏密码" : "显示密码"} onClick={() => setShowPassword(!showPassword)}>{showPassword ? "隐藏" : "显示"}</button></div></label>
              <div className="signin-form-meta"><span>接下来将进行图片验证</span><a href="https://jaccount.sjtu.edu.cn/profile/#/find" target="_blank" rel="noreferrer">忘记密码？</a></div>
              <button className="button button-primary signin-submit" disabled={busy}>{busy ? "正在连接…" : "开始登录 →"}</button>
            </form>}
          </div>}
        {error && <p className="signin-feedback is-error" role="alert">{error}</p>}
        {message && !error && mode === "password" && <p className="signin-feedback" role="status">{message}</p>}
        <div className="signin-privacy"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="m10 2 6 3v5c0 4-6 7-6 7s-6-3-6-7V5l6-3Z" /><path d="m7 9 2 2 4-4" /></svg><p>通过交大统一身份认证连接<br />密码不会保存在这里</p></div>
      </section>
    </div>
    <footer className="signin-footer"><span>LESS PLANNING. MORE PLAY.</span><span>属于你的交大运动日常</span></footer>
  </main>;
}
