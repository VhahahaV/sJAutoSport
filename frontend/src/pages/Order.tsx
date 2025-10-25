import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  api,
  type OrderResponse,
  type Preset,
  type UserSummary,
} from "../lib/api";
import { buildDayOffsetOptions, buildHourOptions, DEFAULT_HOURS } from "../lib/options";
import DebugPanel from "../components/DebugPanel";

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
  const [debugRequest, setDebugRequest] = useState<unknown>();
  const [debugResponse, setDebugResponse] = useState<unknown>();
  const [debugError, setDebugError] = useState<string | null>(null);

  const dateOptions = useMemo(() => buildDayOffsetOptions(), []);
  const hourOptions = useMemo(() => buildHourOptions(DEFAULT_HOURS), []);

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
      setDebugError(null);
      setResult(null);
      const payload = {
        preset: Number(selectedPreset),
        date: selectedDate,
        start_time: `${selectedHour.toString().padStart(2, "0")}:00`,
        user: selectedUser || undefined,
      };
      setDebugRequest(payload);
      setDebugResponse(undefined);
      const response = await api.createOrder(payload);
      setResult(response);
      setDebugResponse(response);
    } catch (err) {
      setResult(null);
      const message = (err as Error).message;
      setError(message);
      setDebugError(message);
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
          <label className="form-label">
            <span>选择预设</span>
            <select
              value={selectedPreset}
              onChange={(event) => {
                const value = event.target.value;
                setSelectedPreset(value ? Number(value) : "");
              }}
              className="input"
            >
              {presets.map((preset) => (
                <option key={preset.index} value={preset.index}>
                  {preset.index}. {preset.venue_name} / {preset.field_type_name}
                </option>
              ))}
            </select>
          </label>

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

          <label className="form-label">
            <span>指定用户（可选）</span>
            <select
              value={selectedUser}
              onChange={(event) => setSelectedUser(event.target.value)}
              className="input"
            >
              <option value="">使用默认</option>
              {users.map((user, idx) => (
                <option key={`${user.username || user.nickname || idx}`} value={user.username || user.nickname || ""}>
                  {user.nickname || user.username || "未命名"}
                  {user.is_active ? "（当前）" : ""}
                </option>
              ))}
            </select>
          </label>

          <div className="form-actions">
            <button className="button button-primary" type="submit" disabled={loading}>
              {loading ? "下单中..." : "提交订单"}
            </button>
          </div>
        </form>
        {users.length > 0 ? (
          <div className="muted-text" style={{ gridColumn: "1 / -1" }}>
            已保存用户： {users.map((user) => user.nickname || user.username || "未命名").join(" / ")}
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

      <DebugPanel
        title="调试信息"
        request={debugRequest}
        response={debugResponse}
        error={debugError}
      />
    </>
  );
};

export default OrderPage;
