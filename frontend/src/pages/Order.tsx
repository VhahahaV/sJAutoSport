import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  api,
  type OrderResponse,
  type Preset,
  type UserSummary,
} from "../lib/api";
import { BOOKING_HOURS, buildDayOffsetOptions, buildHourOptions } from "../lib/options";
import PresetSelector from "../components/PresetSelector";
import { fireConfetti } from "../lib/effects";

const OrderPage = () => {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [users, setUsers] = useState<UserSummary[]>([]);
  const [selectedPreset, setSelectedPreset] = useState<number | "">("");
  const [selectedUser, setSelectedUser] = useState<string>("");
  const [selectedDate, setSelectedDate] = useState<string>("0");
  const [selectedHour, setSelectedHour] = useState<number>(18);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<OrderResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Debug states removed per requirements

  const dateOptions = useMemo(() => buildDayOffsetOptions(), []);
  const hourOptions = useMemo(() => buildHourOptions(BOOKING_HOURS), []);
  const userOptions = useMemo(
    () =>
      users
        .map((user, index) => {
          const username = user.username?.trim();
          const nickname = user.nickname?.trim();
          const compactUsername =
            username && username.includes("@") ? username.split("@", 1)[0] : username;
          const value = username || nickname || compactUsername || "";
          if (!value) {
            return null;
          }
          const label = nickname || compactUsername || `用户 ${index + 1}`;
          const description =
            username && nickname && username !== nickname
              ? username
              : username && compactUsername !== username
                ? username
                : undefined;
          return {
            id: value,
            value,
            label,
            description,
          };
        })
        .filter((entry): entry is { id: string; value: string; label: string; description?: string } => entry !== null),
    [users],
  );

  useEffect(() => {
    const load = async () => {
      try {
        const [presetResp, userResp] = await Promise.all([
          api.getPresets(),
          api.listUsers(),
        ]);
        setPresets(presetResp.presets);
        if (presetResp.presets.length > 0) {
          setSelectedPreset(presetResp.presets[0].index);
        }
        setUsers(userResp.users);
      } catch (err) {
        setError((err as Error).message);
      }
    };
    void load();
  }, []);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedPreset || !selectedDate) {
      setError("请完整填写预设、日期与开始时间");
      return;
    }
    try {
      setLoading(true);
      setError(null);
      setResult(null);
      const payload = {
        preset: Number(selectedPreset),
        date: selectedDate,
        start_time: `${selectedHour.toString().padStart(2, "0")}:00`,
        user: selectedUser || undefined,
      };
      const response = await api.createOrder(payload);
      setResult(response);
      if (response.success) {
        fireConfetti({ origin: { x: 0.75, y: 0.22 }, particleCount: 36 });
      }
    } catch (err) {
      setResult(null);
      const message = (err as Error).message;
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <div className="content-header">
        <div>
          <h2>立即预订</h2>
          <p className="content-subtitle">使用预设快速下单，可选择指定登录用户。</p>
        </div>
      </div>

      <div className="panel">
        <form onSubmit={handleSubmit} className="form-grid">
          <div className="form-label form-label--full">
            <span>选择预设</span>
            <PresetSelector
              presets={presets}
              value={selectedPreset}
              onChange={(nextPreset) => setSelectedPreset(nextPreset)}
            />
          </div>

          <label className="form-label">
            <span>日期</span>
            <select
              value={selectedDate}
              onChange={(event) => setSelectedDate(event.target.value)}
              className="input"
            >
              {dateOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>

          <label className="form-label">
            <span>开始时间</span>
            <select
              value={selectedHour}
              onChange={(event) => setSelectedHour(Number(event.target.value))}
              className="input"
            >
              {hourOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>

          <div className="form-label form-label--full">
            <span>指定用户（可选）</span>
            <div className="toggle-group toggle-group--wrap">
              <button
                type="button"
                className={`toggle-button ${selectedUser ? "" : "is-active"}`}
                onClick={() => setSelectedUser("")}
              >
                所有用户
              </button>
              {userOptions.map((user) => {
                const isActive = selectedUser === user.value && user.value !== "";
                return (
                  <button
                    key={user.id}
                    type="button"
                    className={`toggle-button ${isActive ? "is-active" : ""}`}
                    onClick={() => setSelectedUser(user.value)}
                    title={user.description || undefined}
                  >
                    {user.label}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="form-actions">
            <button className="button button-primary" type="submit" disabled={loading}>
              {loading ? "下单中..." : "提交订单"}
            </button>
          </div>
        </form>
        {users.length > 0 ? (
          <div className="muted-text" style={{ gridColumn: "1 / -1" }}>
            已保存用户：{" "}
            {users
              .map((user, index) => {
                const nickname = user.nickname?.trim();
                const username = user.username?.trim();
                if (nickname) {
                  return nickname;
                }
                if (username) {
                  return username.includes("@") ? username.split("@", 1)[0] : username;
                }
                return `用户 ${index + 1}`;
              })
              .join(" / ")}
          </div>
        ) : null}
      </div>

      {error ? (
        <div className="panel notice notice-error">
          <strong>下单失败</strong>
          <span>{error}</span>
        </div>
      ) : null}

      {result ? (
        <div className="panel">
          <div style={{ fontWeight: 600, marginBottom: "6px" }}>{result.success ? "预订成功" : "预订失败"}</div>
          <div>{result.message}</div>
          {result.order_id ? <div>订单号：{result.order_id}</div> : null}
        </div>
      ) : null}

    </>
  );
};

export default OrderPage;
