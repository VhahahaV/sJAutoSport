import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  api,
  type MonitorInfo,
  type MonitorRequestBody,
  type Preset,
  type UserSummary,
} from "../lib/api";
import { buildDayOffsetOptions, buildHourOptions } from "../lib/options";
import PresetSelector from "../components/PresetSelector";

// 只显示 12:00 到 21:00
const PREFERRED_HOURS = [12, 13, 14, 15, 16, 17, 18, 19, 20, 21];
const MAX_SLOT_PREVIEW = 5;
// Debug panel removed per requirements

type UserOption = {
  id: string;
  label: string;
  description?: string;
};

type SlotPreview = {
  date?: unknown;
  start?: unknown;
  end?: unknown;
  field_name?: unknown;
  remain?: unknown;
  price?: unknown;
};

const toSlotPreviewList = (value: unknown): SlotPreview[] => {
  if (Array.isArray(value)) {
    return value as SlotPreview[];
  }
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      return Array.isArray(parsed) ? (parsed as SlotPreview[]) : [];
    } catch {
      return [];
    }
  }
  return [];
};

const MonitorPage = () => {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [users, setUsers] = useState<UserSummary[]>([]);
  const [monitors, setMonitors] = useState<MonitorInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  // Debug states removed per requirements

  const [monitorId, setMonitorId] = useState("monitor-" + Date.now().toString().slice(-6));
  const [presetIndex, setPresetIndex] = useState<number | "">("");
  const [intervalMinutes, setIntervalMinutes] = useState(15);
  const [autoBook, setAutoBook] = useState(true);  // 默认打开
  const [requireAllUsersSuccess, setRequireAllUsersSuccess] = useState(false);
  const [includeAllTargets, setIncludeAllTargets] = useState(true);
  const [selectedTargetUsers, setSelectedTargetUsers] = useState<string[]>([]);
  const [selectedExcludeUsers, setSelectedExcludeUsers] = useState<string[]>([]);
  const [selectedPreferredHours, setSelectedPreferredHours] = useState<number[]>([]);
  const [selectedPreferredDays, setSelectedPreferredDays] = useState<number[]>([]);
  const [maxRuntimeMinutes, setMaxRuntimeMinutes] = useState<number | "">("");
  const [runUntil, setRunUntil] = useState<string>("");
  const [deleteAllLoading, setDeleteAllLoading] = useState(false);

  const monitorHourOptions = useMemo(() => buildHourOptions(PREFERRED_HOURS), []);
  const dayOptions = useMemo(
    () => buildDayOffsetOptions().map((option) => ({ value: Number(option.value), label: option.label })),
    [],
  );

  const userOptions = useMemo<UserOption[]>(
    () =>
      users.map((user, index) => {
        const id = (user.nickname || user.username || `user-${index}`).trim();
        const nickname = user.nickname?.trim();
        const username = user.username?.trim();
        const label = nickname || username || `用户 ${index + 1}`;
        const description = nickname && username ? username : undefined;
        return { id, label, description };
      }),
    [users],
  );

  const loadMonitors = async () => {
    try {
      const response = await api.listMonitors();
      const items =
        (Array.isArray(response.monitors) ? (response.monitors as MonitorInfo[]) : []) ||
        (response.monitor_info ? [response.monitor_info] : []);
      setMonitors(items);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  useEffect(() => {
    const init = async () => {
      try {
        const [presetResp, userResp] = await Promise.all([api.getPresets(), api.listUsers()]);
        setPresets(presetResp.presets);
        if (presetResp.presets.length > 0) {
          setPresetIndex(presetResp.presets[0].index);
        }
        setUsers(userResp.users);
      } catch (err) {
        setError((err as Error).message);
      }
      await loadMonitors();
    };
    void init();
  }, []);

  const resetForm = () => {
    setMonitorId("");
    setIntervalMinutes(4);
    setAutoBook(false);
    setIncludeAllTargets(true);
    setSelectedTargetUsers([]);
    setSelectedExcludeUsers([]);
    setSelectedPreferredHours([]);
    setSelectedPreferredDays([]);
    setMaxRuntimeMinutes("");
    setRunUntil("");
  };

  const togglePreferredHour = (hour: number) => {
    setSelectedPreferredHours((prev) =>
      prev.includes(hour) ? prev.filter((item) => item !== hour) : [...prev, hour].sort((a, b) => a - b),
    );
  };

  const togglePreferredDay = (day: number) => {
    setSelectedPreferredDays((prev) =>
      prev.includes(day) ? prev.filter((item) => item !== day) : [...prev, day].sort((a, b) => a - b),
    );
  };

  const toggleTargetUser = (userId: string) => {
    setIncludeAllTargets(false);
    setSelectedTargetUsers((prev) =>
      prev.includes(userId)
        ? prev.filter((item) => item !== userId)
        : [...prev, userId]
    );
  };

  const toggleExcludeUser = (userId: string) => {
    setSelectedExcludeUsers((prev) =>
      prev.includes(userId)
        ? prev.filter((item) => item !== userId)
        : [...prev, userId]
    );
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!monitorId.trim()) {
      setError("监控任务 ID 不能为空");
      return;
    }
    try {
      setLoading(true);
      setError(null);
      setMessage(null);

      const targetUsersPayload = includeAllTargets ? undefined : selectedTargetUsers;
      const excludeUsersPayload = selectedExcludeUsers.length > 0 ? selectedExcludeUsers : undefined;
      const preferredHoursPayload = selectedPreferredHours.length > 0 ? selectedPreferredHours : undefined;
      const preferredDaysPayload = selectedPreferredDays.length > 0 ? selectedPreferredDays : undefined;

      const payload: MonitorRequestBody = {
        monitor_id: monitorId.trim(),
        preset: presetIndex ? Number(presetIndex) : undefined,
        interval_seconds: intervalMinutes * 60,
        auto_book: autoBook,
        require_all_users_success: requireAllUsersSuccess,
        target_users: targetUsersPayload,
        exclude_users: excludeUsersPayload,
        preferred_hours: preferredHoursPayload,
        preferred_days: preferredDaysPayload,
      };

      if (maxRuntimeMinutes !== "") {
        const minutes = Number(maxRuntimeMinutes);
        if (!Number.isNaN(minutes) && minutes > 0) {
          payload.max_runtime_minutes = minutes;
        }
      }

      if (runUntil.trim()) {
        payload.end_time = runUntil.trim();
      }

      await api.createMonitor(payload);
      setMessage("监控任务已创建");
      resetForm();
      await loadMonitors();
    } catch (err) {
      const messageText = (err as Error).message;
      setError(messageText);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      setLoading(true);
      setError(null);
      setMessage(null);
      await api.deleteMonitor(id);
      setMessage(`已停止监控任务 ${id}`);
      await loadMonitors();
    } catch (err) {
      const messageText = (err as Error).message;
      setError(messageText);
    } finally {
      setLoading(false);
    }
  };

  const handlePause = async (id: string) => {
    try {
      setLoading(true);
      setError(null);
      setMessage(null);
      await api.pauseMonitor(id);
      setMessage(`已暂停监控任务 ${id}`);
      await loadMonitors();
    } catch (err) {
      const messageText = (err as Error).message;
      setError(messageText);
    } finally {
      setLoading(false);
    }
  };

  const handleResume = async (id: string) => {
    try {
      setLoading(true);
      setError(null);
      setMessage(null);
      await api.resumeMonitor(id);
      setMessage(`已恢复监控任务 ${id}`);
      await loadMonitors();
    } catch (err) {
      const messageText = (err as Error).message;
      setError(messageText);
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteAll = async () => {
    if (!confirm("确定要删除所有任务吗？此操作不可撤销。")) {
      return;
    }

    try {
      setDeleteAllLoading(true);
      setError(null);
      setMessage(null);
      const monitorIds = monitors.map((monitor, index) => {
        const info = monitor as Record<string, unknown>;
        return String(info.id ?? info.monitor_id ?? index);
      });

      if (monitorIds.length === 0) {
        setMessage("当前没有正在运行的监控任务");
        return;
      }

      const results = await Promise.allSettled(
        monitorIds.map((id) => api.deleteMonitor(id)),
      );

      const failedIds = results
        .map((result, idx) => (result.status === "rejected" ? monitorIds[idx] : null))
        .filter((id): id is string => Boolean(id));
      const successCount = monitorIds.length - failedIds.length;

      if (successCount > 0) {
        setMessage(`已停止 ${successCount} 个监控任务`);
      }
      if (failedIds.length > 0) {
        setError(`以下任务停止失败：${failedIds.join(", ")}`);
      }

      // 清理 JobManager 中的残留记录（忽略返回结果，避免阻塞）
      try {
        await api.deleteAllJobs("monitor", true);
      } catch (cleanupError) {
        console.warn("清理监控任务记录失败：", cleanupError);
      }

      await loadMonitors();
    } catch (err) {
      const messageText = (err as Error).message;
      setError(messageText);
    } finally {
      setDeleteAllLoading(false);
    }
  };

  const formatHourList = (hours: unknown): string => {
    if (!Array.isArray(hours) || hours.length === 0) {
      return "-";
    }
    return (hours as number[])
      .map((value) => `${value.toString().padStart(2, "0")}:00`)
      .join(", ");
  };

  const formatDayList = (days: unknown): string => {
    if (!Array.isArray(days) || days.length === 0) {
      return "-";
    }
    const labelMap = new Map<number, string>(dayOptions.map((option) => [option.value, option.label]));
    return (days as number[])
      .map((day) => labelMap.get(day) || String(day))
      .join(", ");
  };

  const formatSlotPreview = (slots: unknown): string[] => {
    if (!Array.isArray(slots) || slots.length === 0) {
      return [];
    }
    return (slots as SlotPreview[])
      .slice(0, MAX_SLOT_PREVIEW)
      .map((slot) => {
        const date = slot.date ?? "?";
        const start = slot.start ?? "?";
        const end = slot.end ?? "?";
        const field = slot.field_name ?? "";
        const remain = slot.remain ?? "";
        const price = slot.price ?? "";
        const suffixParts = [
          remain !== "" ? `余${remain}` : "",
          price !== "" ? `¥${price}` : "",
        ].filter(Boolean);
        const suffix = suffixParts.length ? ` | ${suffixParts.join(" ")}` : "";
        return `${date} ${start}-${end}${field ? ` | ${field}` : ""}${suffix}`;
      });
  };

  const formatDateTime = (value: unknown): string => {
    if (!value) {
      return "-";
    }
    const text = String(value);
    const parsed = new Date(text);
    if (Number.isNaN(parsed.getTime())) {
      return text;
    }
    return parsed.toLocaleString();
  };

  return (
    <>
      <div className="content-header">
        <div>
          <h2>监控任务</h2>
          <p className="content-subtitle">
            启动后台监控，持续检查目标场次并自动抢票。
          </p>
        </div>
      </div>

      <div className="panel">
        <form onSubmit={handleSubmit} className="form-grid">
          <label className="form-label">
            <span>任务 ID</span>
            <input
              value={monitorId}
              onChange={(event) => setMonitorId(event.target.value)}
              placeholder="例如 monitor-001"
              className="input"
            />
          </label>

          <div className="form-label form-label--full">
            <span>预设</span>
            <PresetSelector
              presets={presets}
              value={presetIndex}
              onChange={(nextPreset) => setPresetIndex(nextPreset)}
              onClear={() => setPresetIndex("")}
            />
          </div>

          <label className="form-label">
            <span>监控间隔（分钟）</span>
            <select
              value={intervalMinutes}
              onChange={(event) => setIntervalMinutes(Number(event.target.value))}
              className="input"
            >
              <option value={5}>5分钟</option>
              <option value={10}>10分钟</option>
              <option value={15}>15分钟</option>
              <option value={20}>20分钟</option>
              <option value={25}>25分钟</option>
              <option value={30}>30分钟</option>
              <option value={60}>60分钟</option>
            </select>
          </label>

          <label className="form-label">
            <span>最长运行时长（分钟，可选）</span>
            <input
              type="number"
              min={1}
              max={1440}
              className="input"
              value={maxRuntimeMinutes === "" ? "" : String(maxRuntimeMinutes)}
              onChange={(event) => {
                const value = event.target.value;
                setMaxRuntimeMinutes(value === "" ? "" : Number(value));
              }}
              placeholder="例如 120"
            />
          </label>

          <label className="form-label">
            <span>结束时间（可选）</span>
            <input
              type="datetime-local"
              className="input"
              value={runUntil}
              onChange={(event) => setRunUntil(event.target.value)}
            />
            <span className="muted-text">留空时，系统会在目标时段结束后自动停止</span>
          </label>

          <div className="panel" style={{ gridColumn: "1 / -1", border: "2px solid #F97316", background: "#FFF7ED", padding: "16px" }}>
            <label style={{ display: "flex", alignItems: "center", gap: "12px", fontWeight: "600", fontSize: "16px" }}>
              <input 
                type="checkbox" 
                checked={autoBook} 
                onChange={(event) => setAutoBook(event.target.checked)}
                style={{ width: "20px", height: "20px" }}
              />
              <span style={{ color: "#EA580C" }}>🤖 自动预订 - 发现可用场次时自动下单</span>
            </label>
            {autoBook && (
              <label style={{ display: "flex", alignItems: "center", gap: "12px", marginTop: "12px", fontSize: "14px" }}>
                <input 
                  type="checkbox" 
                  checked={requireAllUsersSuccess} 
                  onChange={(event) => setRequireAllUsersSuccess(event.target.checked)}
                  style={{ width: "18px", height: "18px" }}
                />
                <span style={{ color: "#0891B2" }}>
                  ✓ 要求所有用户都成功 - 所有指定账号都抢到场次才算任务完成，并自动限制开始时间相差不超过 1 小时
                </span>
              </label>
            )}
          </div>

          <fieldset className="fieldset" style={{ gridColumn: "1 / -1" }}>
            <legend>指定用户</legend>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "12px", alignItems: "center" }}>
              <label style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                <input
                  type="checkbox"
                  checked={includeAllTargets}
                  onChange={(event) => {
                    const checked = event.target.checked;
                    setIncludeAllTargets(checked);
                    if (checked) {
                      setSelectedTargetUsers([]);
                    }
                  }}
                />
                所有用户
              </label>
              {userOptions.map((user) => (
                <label key={user.id} style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                  <input
                    type="checkbox"
                    checked={!includeAllTargets && selectedTargetUsers.includes(user.id)}
                    disabled={includeAllTargets}
                    onChange={() => toggleTargetUser(user.id)}
                  />
                  <span>
                    {user.label}
                    {user.description ? `（${user.description}）` : ""}
                  </span>
                </label>
              ))}
            </div>
          </fieldset>

          <fieldset className="fieldset" style={{ gridColumn: "1 / -1" }}>
            <legend>排除用户</legend>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "12px" }}>
              {userOptions.map((user) => (
                <label key={user.id} style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                  <input
                    type="checkbox"
                    checked={selectedExcludeUsers.includes(user.id)}
                    onChange={() => toggleExcludeUser(user.id)}
                  />
                  <span>
                    {user.label}
                    {user.description ? `（${user.description}）` : ""}
                  </span>
                </label>
              ))}
            </div>
          </fieldset>

          <fieldset className="fieldset" style={{ gridColumn: "1 / -1" }}>
            <legend>优先时间段</legend>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "12px" }}>
              {monitorHourOptions.map((option) => (
                <label key={option.value} style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                  <input
                    type="checkbox"
                    checked={selectedPreferredHours.includes(option.value)}
                    onChange={() => togglePreferredHour(option.value)}
                  />
                  {option.label}
                </label>
              ))}
            </div>
          </fieldset>

          <fieldset className="fieldset" style={{ gridColumn: "1 / -1" }}>
            <legend>优先天数</legend>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "12px" }}>
              {dayOptions.map((option) => (
                <label key={option.value} style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                  <input
                    type="checkbox"
                    checked={selectedPreferredDays.includes(option.value)}
                    onChange={() => togglePreferredDay(option.value)}
                  />
                  {option.label}
                </label>
              ))}
            </div>
          </fieldset>

          <div className="form-actions">
            <button className="button button-primary" type="submit" disabled={loading}>
              {loading ? "提交中..." : "创建监控"}
            </button>
          </div>
        </form>
      </div>

      {error ? (
        <div className="panel notice notice-error">
          <strong>操作失败</strong>
          <span>{error}</span>
        </div>
      ) : null}

      {message ? (
        <div className="panel" style={{ border: "1px solid rgba(255, 159, 209, 0.3)", background: "rgba(255, 245, 250, 0.92)" }}>
          {message}
        </div>
      ) : null}

      <section className="section">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
          <h3>当前监控任务</h3>
          {monitors.length > 0 && (
            <button
              className="button button-danger"
              type="button"
              onClick={handleDeleteAll}
              disabled={deleteAllLoading || loading}
              style={{ fontSize: "14px", padding: "8px 16px" }}
            >
              {deleteAllLoading ? "删除中..." : "删除所有任务"}
            </button>
          )}
        </div>
        <div className="panel">
          {monitors.length === 0 ? (
            <span style={{ color: "#667085" }}>暂无监控任务。</span>
          ) : (
            <div className="card-scroll">
              {monitors.map((monitor, index) => {
                const info = monitor as Record<string, unknown>;
                const monitorKey = String(info.id ?? info.monitor_id ?? index);
                const presetLabel =
                  info.preset != null
                    ? String(info.preset)
                    : info.preset_index != null
                      ? String(info.preset_index)
                      : "自定义";
                const status = String(info.status ?? "unknown");
                const statusLower = status.toLowerCase();
                const statusClass =
                  statusLower === "running"
                    ? "chip-success"
                    : statusLower === "paused"
                      ? "chip-info"
                      : statusLower === "completed"
                        ? "chip-success"
                        : "chip-warning";
                const rawInterval = Number(info.interval_seconds ?? info.interval ?? 0) || 0;
                const intervalMinutesDisplay = rawInterval
                  ? (rawInterval / 60).toFixed(rawInterval % 60 === 0 ? 0 : 1)
                  : "-";
                const autoBookFlag = Boolean(info.auto_book);
                const lastCheck = info.last_check ? String(info.last_check) : "未执行";
                const resolved = (info.resolved as Record<string, unknown>) || {};
                const resolvedLabel = resolved.label || resolved.venue_name || "目标";
                const preferredHours = info.preferred_hours;
                const preferredDays = info.preferred_days;
                const targetUserList = Array.isArray(info.target_users) ? (info.target_users as string[]) : [];
                const excludeUserList = Array.isArray(info.exclude_users) ? (info.exclude_users as string[]) : [];
                const parsedSlots = toSlotPreviewList(info.found_slots);
                const slotPreview = formatSlotPreview(parsedSlots);
                const runtimeLimit = info.max_runtime_minutes ?? info.maxRuntimeMinutes;
                const runUntilValue = (info.run_until as string) || (info.auto_stop_at as string) || "";

                const actionButtons = () => {
                  if (statusLower === "running") {
                    return (
                      <>
                        <button
                          className="button button-secondary"
                          type="button"
                          onClick={() => handlePause(monitorKey)}
                          disabled={loading}
                        >
                          暂停任务
                        </button>
                        <button
                          className="button button-danger"
                          type="button"
                          onClick={() => handleDelete(monitorKey)}
                          disabled={loading}
                        >
                          停止任务
                        </button>
                      </>
                    );
                  }
                  if (statusLower === "paused") {
                    return (
                      <>
                        <button
                          className="button button-primary"
                          type="button"
                          onClick={() => handleResume(monitorKey)}
                          disabled={loading}
                        >
                          恢复任务
                        </button>
                        <button
                          className="button button-danger"
                          type="button"
                          onClick={() => handleDelete(monitorKey)}
                          disabled={loading}
                        >
                          删除任务
                        </button>
                      </>
                    );
                  }
                  return (
                    <button
                      className="button button-danger"
                      type="button"
                      onClick={() => handleDelete(monitorKey)}
                      disabled={loading}
                    >
                      删除任务
                    </button>
                  );
                };

                return (
                  <div key={monitorKey} className="monitor-card">
                    <div className="monitor-card-grid">
                      <div>
                        <strong>ID：</strong>
                        {monitorKey}
                      </div>
                      <div>
                        <strong>目标：</strong>
                        {String(resolvedLabel || "-")}
                      </div>
                      <div>
                        <strong>预设：</strong>
                        {presetLabel}
                      </div>
                      <div>
                        <strong>状态：</strong>
                        <span className={`chip ${statusClass}`}>{status}</span>
                      </div>
                      <div>
                        <strong>间隔：</strong>
                        {intervalMinutesDisplay} 分钟
                      </div>
                      <div>
                        <strong>自动预订：</strong>
                        {autoBookFlag ? "是" : "否"}
                      </div>
                      <div>
                        <strong>最后检查：</strong>
                        {lastCheck}
                      </div>
                      <div>
                        <strong>最长运行：</strong>
                        {runtimeLimit ? `${runtimeLimit} 分钟` : "未设置"}
                      </div>
                      <div>
                        <strong>结束时间：</strong>
                        {runUntilValue ? formatDateTime(runUntilValue) : "目标时间结束后"}
                      </div>
                      <div>
                        <strong>优先时段：</strong>
                        {formatHourList(preferredHours)}
                      </div>
                      <div>
                        <strong>优先天数：</strong>
                        {formatDayList(preferredDays)}
                      </div>
                      <div>
                        <strong>指定账号：</strong>
                        {targetUserList.length ? targetUserList.join(", ") : "全部"}
                      </div>
                      <div>
                        <strong>排除账号：</strong>
                        {excludeUserList.length ? excludeUserList.join(", ") : "-"}
                      </div>
                      {slotPreview.length > 0 ? (
                        <div style={{ gridColumn: "1 / -1" }}>
                          <strong>最新可用：</strong>
                          <div className="monitor-card-slots">
                            {slotPreview.map((line, idx) => (
                              <span key={`${monitorKey}-slot-${idx}`} style={{ color: "#475467" }}>
                                {line}
                              </span>
                            ))}
                          </div>
                        </div>
                      ) : null}
                      <div className="monitor-card-actions">
                        {actionButtons()}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </section>

    </>
  );
};

export default MonitorPage;
