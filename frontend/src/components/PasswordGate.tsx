import type { PropsWithChildren, FormEvent } from "react";
import { useEffect, useMemo, useState } from "react";

const GATE_KEY = "sja.portal.unlocked";

const resolvePassword = () =>
  (typeof import.meta !== "undefined" && import.meta.env?.VITE_PORTAL_PASSWORD) || "";

const PasswordGate = ({ children }: PropsWithChildren) => {
  const requiredPassword = useMemo(resolvePassword, []);
  const [ready, setReady] = useState(() => (requiredPassword ? false : true));
  const [unlocked, setUnlocked] = useState(false);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!requiredPassword) {
      setUnlocked(true);
      setReady(true);
      return;
    }
    if (typeof window === "undefined") return;
    const stored = window.localStorage.getItem(GATE_KEY);
    if (stored === "1") {
      setUnlocked(true);
    }
    setReady(true);
  }, [requiredPassword]);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!requiredPassword) {
      setUnlocked(true);
      return;
    }
    if (password === requiredPassword) {
      if (typeof window !== "undefined") {
        window.localStorage.setItem(GATE_KEY, "1");
      }
      setUnlocked(true);
      setError(null);
      return;
    }
    setError("密码不正确，请重试。");
  };

  if (!ready) {
    return null;
  }

  if (unlocked) {
    return <>{children}</>;
  }

  return (
    <div className="password-gate">
      <div className="password-gate__panel">
        <div className="password-gate__emoji" aria-hidden>
          🔐
        </div>
        <h1>访问受限</h1>
        <p>请输入访问密码进入控制台。</p>
        <form onSubmit={handleSubmit} className="password-gate__form">
          <input
            autoFocus
            type="password"
            className="input"
            placeholder="输入访问密码"
            value={password}
            onChange={(event) => {
              setPassword(event.target.value);
              setError(null);
            }}
          />
          {error ? <div className="notice notice-error">{error}</div> : null}
          <button className="button button-primary" type="submit">
            解锁
          </button>
        </form>
        <span className="password-gate__hint">提示：密码由运营人员配置在环境变量 `VITE_PORTAL_PASSWORD` 中。</span>
      </div>
    </div>
  );
};

export default PasswordGate;
