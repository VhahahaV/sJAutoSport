import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import {
  api,
  type AggregatedSlotEntry,
  type AggregatedSlotsByDay,
  type Preset,
  type SlotQueryResponse,
} from "../lib/api";
import { buildDayOffsetOptions, buildHourOptions, DEFAULT_HOURS } from "../lib/options";
import PresetSelector from "../components/PresetSelector";

type StreamChunk =
  | { type: "resolved"; resolved: SlotQueryResponse["resolved"] }
  | { type: "day"; date: string; entries: AggregatedSlotEntry[] }
  | { type: "complete" };

const formatPriceRange = (entry: AggregatedSlotEntry): string => {
  if (entry.min_price == null && entry.max_price == null) {
    return "-";
  }
  if (entry.min_price != null && entry.max_price != null) {
    if (Math.abs(entry.min_price - entry.max_price) < 1e-6) {
      return `¥${entry.min_price.toFixed(0)}`;
    }
    return `¥${entry.min_price.toFixed(0)} - ¥${entry.max_price.toFixed(0)}`;
  }
  const price = entry.min_price ?? entry.max_price ?? 0;
  return `¥${price.toFixed(0)}`;
};

const formatAvailability = (entry: AggregatedSlotEntry): string => {
  if (entry.available_count === entry.site_count) {
    return `${entry.available_count}`;
  }
  return `${entry.available_count}/${entry.site_count}`;
};

const SlotsPage = () => {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [selectedPreset, setSelectedPreset] = useState<number | "">("");
  const [selectedDate, setSelectedDate] = useState<string>("0");
  const [selectedHour, setSelectedHour] = useState<number | "">("");
  const [showFull, setShowFull] = useState(false);
  const [allDays, setAllDays] = useState(false);

  const [resolved, setResolved] = useState<SlotQueryResponse["resolved"] | null>(null);
  const [aggregatedDays, setAggregatedDays] = useState<AggregatedSlotsByDay[]>([]);
  const [loading, setLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const streamingController = useRef<AbortController | null>(null);
  const hasResultsRef = useRef(false);

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

  useEffect(() => () => {
    streamingController.current?.abort();
  }, []);

  const resetQueryState = () => {
    setResolved(null);
    setAggregatedDays([]);
    setMessage(null);
    hasResultsRef.current = false;
  };

  const upsertAggregatedDay = (payload: AggregatedSlotsByDay) => {
    setAggregatedDays((prev) => {
      const next = prev.filter((day) => day.date !== payload.date);
      next.push(payload);
      next.sort((a, b) => a.date.localeCompare(b.date));
      return next;
    });
  };

  const handleStandardResponse = (response: SlotQueryResponse) => {
    setResolved(response.resolved);
    const days = response.aggregated_days ?? [];
    setAggregatedDays(days);
    hasResultsRef.current = days.some((day) => day.entries.length > 0);
    if (!hasResultsRef.current) {
      setMessage("本次查询未找到可预订的场次。");
    }
  };

  const streamSlots = async (
    payload: Record<string, unknown>,
    controller: AbortController,
  ): Promise<void> => {
    setIsStreaming(true);
    const response = await fetch("/api/booking/slots", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...payload, incremental: true }),
      signal: controller.signal,
    });

    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || `查询失败，状态码 ${response.status}`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error("无法读取服务器返回的数据流");
    }

    const decoder = new TextDecoder();
    let buffer = "";
    let completed = false;

    const processLine = (line: string) => {
      if (!line) return;
      const parsed = JSON.parse(line) as StreamChunk;
      if (parsed.type === "resolved") {
        setResolved(parsed.resolved);
        return;
      }
      if (parsed.type === "day") {
        hasResultsRef.current = hasResultsRef.current || parsed.entries.length > 0;
        upsertAggregatedDay({ date: parsed.date, entries: parsed.entries });
        return;
      }
      if (parsed.type === "complete") {
        completed = true;
      }
    };

    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let newlineIndex = buffer.indexOf("\n");
        while (newlineIndex >= 0) {
          const line = buffer.slice(0, newlineIndex).trim();
          buffer = buffer.slice(newlineIndex + 1);
          processLine(line);
          newlineIndex = buffer.indexOf("\n");
        }
      }
      buffer += decoder.decode();
      const finalLine = buffer.trim();
      if (finalLine) {
        processLine(finalLine);
      }
    } finally {
      reader.releaseLock();
    }

    if (!controller.signal.aborted) {
      if (!completed) {
        processLine(JSON.stringify({ type: "complete" }));
      }
      setIsStreaming(false);
      setLoading(false);
      if (!hasResultsRef.current) {
        setMessage("本次查询未找到可预订的场次。");
      }
    }
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    streamingController.current?.abort();

    const controller = new AbortController();
    streamingController.current = controller;

    resetQueryState();
    setError(null);
    setLoading(true);
    setIsStreaming(false);

    const payload = {
      preset: selectedPreset ? Number(selectedPreset) : undefined,
      venue_id: undefined,
      field_type_id: undefined,
      date: allDays ? undefined : selectedDate || undefined,
      start_hour: selectedHour === "" ? undefined : Number(selectedHour),
      show_full: showFull,
      all_days: allDays,
    };

    try {
      if (allDays) {
        await streamSlots(payload, controller);
        return;
      }

      const response = await api.querySlots(payload);
      if (!controller.signal.aborted) {
        handleStandardResponse(response);
      }
    } catch (err) {
      if (controller.signal.aborted) {
        return;
      }
      setLoading(false);
      setIsStreaming(false);
      setError((err as Error).message || "查询失败");
    } finally {
      if (!controller.signal.aborted && !allDays) {
        setLoading(false);
        if (!hasResultsRef.current && !error) {
          setMessage("本次查询未找到可预订的场次。");
        }
      }
    }
  };

  return (
    <>
      <div className="content-header">
        <div>
          <h2>查询场地</h2>
          <p className="content-subtitle">根据场馆运动或自定义条件检索可用时段。</p>
        </div>
      </div>

      <div className="panel">
        <form onSubmit={handleSubmit} className="form-grid">
          <div className="form-label form-label--full">
            <span>选择场馆运动</span>
            <PresetSelector
              presets={presets}
              value={selectedPreset}
              onChange={(nextPreset) => setSelectedPreset(nextPreset)}
            />
          </div>

          <label className="form-label">
            <span>日期</span>
            <select
              value={allDays ? "" : selectedDate}
              onChange={(event) => setSelectedDate(event.target.value)}
              className="input"
              disabled={allDays}
            >
              {dateOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>

          <label style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <input
              type="checkbox"
              checked={allDays}
              onChange={(event) => {
                const checked = event.target.checked;
                setAllDays(checked);
                if (checked) {
                  setSelectedDate("");
                } else {
                  setSelectedDate("0");
                }
              }}
            />
            查询所有日期
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
              {loading ? (isStreaming ? "持续加载..." : "查询中...") : "查询时段"}
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

      {resolved ? (
        <section className="section">
          <h3>结果摘要</h3>
          <div className="panel">
            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              <div>
                <strong>目标</strong>：{resolved.label}
              </div>
              {resolved.preset ? (
                <div>
                  <strong>场馆运动</strong>：{resolved.preset.index} - {resolved.preset.venue_name} / {resolved.preset.field_type_name}
                </div>
              ) : null}
            </div>
          </div>
        </section>
      ) : null}

      {message ? (
        <section className="section">
          <h3>查询结果</h3>
          <div className="panel">
            <span style={{ color: "#667085" }}>{message}</span>
          </div>
        </section>
      ) : null}

      {aggregatedDays.map((day) => (
        <section key={day.date} className="section">
          <h3>{day.date}</h3>
          <div className="panel">
            {day.entries.length === 0 ? (
              <span style={{ color: "#667085" }}>该日期暂无可预订的时间段。</span>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>时间</th>
                    <th>可订场地</th>
                    <th>总余量</th>
                    <th>价格</th>
                  </tr>
                </thead>
                <tbody>
                  {day.entries.map((entry, index) => (
                    <tr key={`${entry.start}-${entry.end}-${index}`}>
                      <td>
                        {entry.start} - {entry.end}
                      </td>
                      <td>{formatAvailability(entry)}</td>
                      <td>{entry.total_remain ?? "-"}</td>
                      <td>{formatPriceRange(entry)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </section>
      ))}
    </>
  );
};

export default SlotsPage;
