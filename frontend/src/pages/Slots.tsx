import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  api,
  type Preset,
  type SlotAvailability,
  type SlotQueryResponse,
} from "../lib/api";
import { buildDayOffsetOptions, buildHourOptions, DEFAULT_HOURS } from "../lib/options";
import DebugPanel from "../components/DebugPanel";

const SlotsPage = () => {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [selectedPreset, setSelectedPreset] = useState<number | "">("");
  const [selectedDate, setSelectedDate] = useState<string>("0");
  const [selectedHour, setSelectedHour] = useState<number | "">("");
  const [showFull, setShowFull] = useState(false);
  const [result, setResult] = useState<SlotQueryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [debugRequest, setDebugRequest] = useState<unknown>();
  const [debugResponse, setDebugResponse] = useState<unknown>();
  const [debugError, setDebugError] = useState<string | null>(null);

  const dateOptions = useMemo(() => buildDayOffsetOptions(), []);
  const hourOptions = useMemo(() => buildHourOptions(DEFAULT_HOURS), []);

  useEffect(() => {
    const loadPresets = async () => {
      try {
        const data = await api.getPresets();
        setPresets(data.presets);
        if (data.presets.length > 0) {
          setSelectedPreset(data.presets[0].index);
        }
      } catch (err) {
        setError((err as Error).message);
      }
    };
    void loadPresets();
  }, []);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedPreset && !selectedDate) {
      setError("请选择预设或提供查询条件");
      return;
    }
    try {
      setLoading(true);
      setError(null);
       setDebugError(null);
      const payload: Record<string, unknown> = {
        show_full: showFull,
      };
      if (selectedPreset) {
        payload.preset = Number(selectedPreset);
      }
      if (selectedDate) {
        payload.date = selectedDate;
      }
      if (selectedHour !== "") {
        payload.start_hour = Number(selectedHour);
      }
      setDebugRequest(payload);
      setDebugResponse(undefined);
      const data = await api.querySlots(payload);
      setResult(data);
      setDebugResponse(data);
    } catch (err) {
      setResult(null);
      setError((err as Error).message);
      setDebugError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const slots: SlotAvailability[] = result?.slots ?? [];
  const noSlotsMessage =
    result && slots.length === 0
      ? "没有找到符合条件的时间段，请尝试调整日期或时间。"
      : null;

  return (
    <>
      <div className="content-header">
        <div>
          <h2>查询场地</h2>
          <p className="content-subtitle">根据预设或自定义条件检索可用时段。</p>
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
            <span>开始小时（可选）</span>
            <select
              value={selectedHour === "" ? "" : Number(selectedHour)}
              onChange={(event) => {
                const value = event.target.value;
                setSelectedHour(value === "" ? "" : Number(value));
              }}
              className="input"
            >
              <option value="">全部</option>
              {hourOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>

          <label style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <input
              type="checkbox"
              checked={showFull}
              onChange={(event) => setShowFull(event.target.checked)}
            />
            显示全部时段
          </label>

          <div className="form-actions">
            <button className="button button-primary" type="submit" disabled={loading}>
              {loading ? "查询中..." : "查询时段"}
            </button>
          </div>
        </form>
      </div>

      {error ? (
        <div className="panel notice notice-error">
          <strong>查询失败</strong>
          <span>{error}</span>
        </div>
      ) : null}

      {result ? (
        <section className="section">
          <h3>结果摘要</h3>
          <div className="panel">
            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              <div>
                <strong>目标</strong>：{result.resolved.label}
              </div>
              {result.resolved.preset ? (
                <div>
                  <strong>预设</strong>：{result.resolved.preset.index} -{" "}
                  {result.resolved.preset.venue_name} / {result.resolved.preset.field_type_name}
                </div>
              ) : null}
            </div>
          </div>
        </section>
      ) : null}

      {noSlotsMessage ? (
        <section className="section">
          <h3>查询结果</h3>
          <div className="panel">
            <span style={{ color: "#667085" }}>{noSlotsMessage}</span>
          </div>
        </section>
      ) : null}

      {slots.length > 0 ? (
        <section className="section">
          <h3>可用时段</h3>
          <div className="panel">
            <table className="table">
              <thead>
                <tr>
                  <th>日期</th>
                  <th>时间</th>
                  <th>场地</th>
                  <th>剩余</th>
                  <th>价格</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                {slots.map((entry, index) => (
                  <tr key={`${entry.slot.slot_id}-${index}`}>
                    <td>{entry.date}</td>
                    <td>
                      {entry.slot.start} - {entry.slot.end}
                    </td>
                    <td>{entry.slot.field_name || "—"}</td>
                    <td>{entry.slot.remain ?? "未知"}</td>
                    <td>{entry.slot.price ?? "未知"}</td>
                    <td>
                      <span
                        className={`chip ${
                          entry.slot.available ? "chip-success" : "chip-warning"
                        }`}
                      >
                        {entry.slot.available ? "可预订" : "占用"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
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

export default SlotsPage;
