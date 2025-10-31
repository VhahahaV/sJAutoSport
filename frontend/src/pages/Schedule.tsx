import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  api,
  type Preset,
  type ScheduleInfo,
  type ScheduleRequestBody,
  type UserSummary,
} from "../lib/api";
import {
  BOOKING_HOURS,
  buildDayOffsetOptions,
  buildHourOptions,
  buildMinuteOptions,
  buildSecondOptions,
  HOURS_24,
} from "../lib/options";
import PresetSelector from "../components/PresetSelector";
import RangeSelector from "../components/RangeSelector";

// 执行小时：支持24小时全覆盖（脚本执行时间）
const EXECUTION_HOURS = HOURS_24;

const START_HOUR_RANGE = {
  min: BOOKING_HOURS[0],
  max: BOOKING_HOURS[BOOKING_HOURS.length - 1],
} as const;

const createScheduleId = () => `schedule-${Date.now().toString(36).slice(-6)}`;

const buildRangeValues = (range: [number, number] | null): number[] | undefined => {
  if (!range) {
    return undefined;
  }
  const start = Math.min(range[0], range[1]);
  const end = Math.max(range[0], range[1]);
  if (start <= START_HOUR_RANGE.min && end >= START_HOUR_RANGE.max) {
    return undefined;
  }
  const values: number[] = [];
  for (let value = start; value <= end; value += 1) {
    values.push(value);
  }
  return values;
};

const formatHourValue = (value: number) => `${value.toString().padStart(2, "0")}:00`;

type UserOption = {
  id: string;
  label: string;
  description?: string;
};
// Debug panel removed per requirements

const SchedulePage = () => {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [schedules, setSchedules] = useState<ScheduleInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  // Debug states removed per requirements

  const [jobId, setJobId] = useState(createScheduleId());
  const [executeHour, setExecuteHour] = useState(12);
  const [executeMinute, setExecuteMinute] = useState(0);
  const [executeSecond, setExecuteSecond] = useState(0);
  const [presetIndex, setPresetIndex] = useState<number | "">("");
  const [selectedDate, setSelectedDate] = useState<string>("7");
  const [startHourRange, setStartHourRange] = useState<[number, number] | null>(null);
  const [availableUsers, setAvailableUsers] = useState<UserSummary[]>([]);
  const [userError, setUserError] = useState<string | null>(null);
  const [userLoading, setUserLoading] = useState(false);
  const [includeAllUsers, setIncludeAllUsers] = useState(true);
  const [selectedUsers, setSelectedUsers] = useState<string[]>([]);
  const [requireAllUsersSuccess, setRequireAllUsersSuccess] = useState(true);
  const userOptions = useMemo(
    () =>
      availableUsers.map((user, index) => {
        const id = (user.username || user.nickname || `user-${index}`).trim();
        const nickname = user.nickname?.trim();
        const username = user.username?.trim();
        const compactUsername =
          username && username.includes("@") ? username.split("@", 1)[0] : username;
        return {
          id,
          label: nickname || compactUsername || `用户 ${index + 1}`,
          description:
            username && nickname
              ? username
              : username && compactUsername !== username
                ? username
                : undefined,
        };
      }),
    [availableUsers],
  );

  const userLabelMap = useMemo(() => {
    const mapping = new Map<string, string>();
    availableUsers.forEach((user, index) => {
      const nickname = user.nickname?.trim();
      const username = user.username?.trim();
      const compact = username && username.includes("@") ? username.split("@", 1)[0] : username;
      const fallback = `用户 ${index + 1}`;
      const label = nickname || compact || username || fallback;
      if (nickname) mapping.set(nickname, nickname);
      if (username) mapping.set(username, label);
      if (compact && compact !== username) mapping.set(compact, compact);
      if (user.key) mapping.set(user.key, label);
    });
    return mapping;
  }, [availableUsers]);

  const executionHourOptions = useMemo(() => buildHourOptions(EXECUTION_HOURS), []);
  const minuteOptions = useMemo(() => buildMinuteOptions(), []);
  const secondOptions = useMemo(() => buildSecondOptions(), []);
  const dayOptions = useMemo(() => buildDayOffsetOptions(), []);

  const toggleUser = (userId: string) => {
    setIncludeAllUsers(false);
    setSelectedUsers((prev) =>
      prev.includes(userId) ? prev.filter((item) => item !== userId) : [...prev, userId]
    );
  };

  const loadSchedules = async () => {
    try {
      const response = await api.listSchedules();
      setSchedules(response.jobs || []);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const loadUsers = async () => {
    try {
      setUserLoading(true);
      setUserError(null);
      const result = await api.listUsers();
      setAvailableUsers(result.users || []);
    } catch (err) {
      setUserError((err as Error).message);
      setAvailableUsers([]);
    } finally {
      setUserLoading(false);
    }
  };

  useEffect(() => {
    const init = async () => {
      try {
        const presetsResp = await api.getPresets();
        setPresets(presetsResp.presets);
        if (presetsResp.presets.length > 0) {
          setPresetIndex(presetsResp.presets[0].index);
        }
      } catch (err) {
        setError((err as Error).message);
      }
      await Promise.all([loadSchedules(), loadUsers()]);
    };
    void init();
  }, []);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!jobId.trim()) {
      setError("任务 ID 不能为空");
      return;
    }
    try {
      setLoading(true);
      setError(null);
      setMessage(null);
      const payload: ScheduleRequestBody = {
        job_id: jobId.trim(),
        hour: executeHour,
        minute: executeMinute,
        second: executeSecond,
        preset: presetIndex ? Number(presetIndex) : undefined,
        date: selectedDate || undefined,
        require_all_users_success: requireAllUsersSuccess,
      };

      const startHoursPayload = buildRangeValues(startHourRange);
      if (startHoursPayload && startHoursPayload.length > 0) {
        payload.start_hours = startHoursPayload;
      }

      if (!includeAllUsers && selectedUsers.length > 0) {
        payload.target_users = selectedUsers;
      }
      
      await api.createSchedule(payload);
      setMessage("定时任务已创建");
      setJobId(createScheduleId());
      setSelectedUsers([]);
      setStartHourRange(null);
      setIncludeAllUsers(true);
      await loadSchedules();
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
      await api.deleteSchedule(id);
      setMessage(`已删除定时任务 ${id}`);
      await loadSchedules();
    } catch (err) {
      const messageText = (err as Error).message;
      setError(messageText);
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <div className="content-header">
        <div>
          <h2>定时任务</h2>
          <p className="content-subtitle">按固定时间执行预订请求，可配合场馆运动快速配置。</p>
        </div>
      </div>

      <div className="panel">
        <form onSubmit={handleSubmit} className="form-grid">
          <label className="form-label">
            <span>任务 ID</span>
            <input
              value={jobId}
              onChange={(event) => setJobId(event.target.value)}
              placeholder="例如 schedule-001"
              className="input"
            />
          </label>

          <div className="form-label form-label--full">
            <span>场馆运动（可选）</span>
            <PresetSelector
              presets={presets}
              value={presetIndex}
              onChange={(nextPreset) => setPresetIndex(nextPreset)}
              onClear={() => setPresetIndex("")}
            />
          </div>

          <label className="form-label">
            <span>预定日期</span>
            <select
              value={selectedDate}
              onChange={(event) => setSelectedDate(event.target.value)}
              className="input"
            >
              <option value="">不指定</option>
              {dayOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>

          <div className="form-label form-label--full">
            <RangeSelector
              min={START_HOUR_RANGE.min}
              max={START_HOUR_RANGE.max}
              value={startHourRange}
              onChange={setStartHourRange}
              label="预定小时（可选）"
              formatValue={formatHourValue}
            />
            <span className="muted-text">未限制时，将使用场馆运动配置的默认开始时间。</span>
          </div>

          <fieldset className="fieldset" style={{ gridColumn: "1 / -1" }}>
            <legend>指定用户（可选）</legend>
            {userError ? <div className="notice notice-error">{userError}</div> : null}
            {userLoading ? <span className="muted-text">加载用户中…</span> : null}
            <div className="toggle-group toggle-group--wrap">
              <button
                type="button"
                className={`toggle-button ${includeAllUsers ? "is-active" : ""}`}
                onClick={() => {
                  setIncludeAllUsers(true);
                  setSelectedUsers([]);
                }}
              >
                所有用户
              </button>
              {userOptions.length === 0 && !userLoading ? (
                <span className="muted-text">暂无可用用户，请先在会话管理页完成登录。</span>
              ) : null}
              {userOptions.map((user) => {
                const isActive = !includeAllUsers && selectedUsers.includes(user.id);
                return (
                  <button
                    key={user.id}
                    type="button"
                    className={`toggle-button ${isActive ? "is-active" : ""}`}
                    onClick={() => toggleUser(user.id)}
                    title={user.description || undefined}
                  >
                    {user.label}
                  </button>
                );
              })}
            </div>
            {!includeAllUsers && selectedUsers.length === 0 ? (
              <span className="muted-text">未选择账号时，将按默认顺序尝试所有可用账号</span>
            ) : null}
          </fieldset>

          {!includeAllUsers && selectedUsers.length > 0 && (
            <div className="panel" style={{ gridColumn: "1 / -1", border: "2px solid #0891B2", background: "#ECFEFF", padding: "16px" }}>
              <label style={{ display: "flex", alignItems: "center", gap: "12px", fontSize: "14px" }}>
                <input 
                  type="checkbox" 
                  checked={requireAllUsersSuccess} 
                  onChange={(event) => setRequireAllUsersSuccess(event.target.checked)}
                  style={{ width: "18px", height: "18px" }}
                />
                <span style={{ color: "#0891B2" }}>
                  ✓ 要求所有用户都成功 - 全部指定账号抢到场次才算任务完成，并会限制预约的开始时间相差不超过 1 小时
                </span>
              </label>
            </div>
          )}

          <div className="form-label form-label--full">
            <span>执行时间</span>
            <div className="inline-field-group">
              <label className="inline-field">
                <span>小时</span>
                <select
                  value={executeHour}
                  onChange={(event) => setExecuteHour(Number(event.target.value))}
                  className="input"
                >
                  {executionHourOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="inline-field">
                <span>分钟</span>
                <select
                  value={executeMinute}
                  onChange={(event) => setExecuteMinute(Number(event.target.value))}
                  className="input"
                >
                  {minuteOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="inline-field">
                <span>秒</span>
                <select
                  value={executeSecond}
                  onChange={(event) => setExecuteSecond(Number(event.target.value))}
                  className="input"
                >
                  {secondOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>

          <div className="form-actions">
            <button className="button button-primary" type="submit" disabled={loading}>
              {loading ? "提交中..." : "创建定时任务"}
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
        <div className="panel">
          {message}
        </div>
      ) : null}

      <section className="section">
        <h3>任务列表</h3>
        <div className="panel">
          {schedules.length === 0 ? (
            <span className="muted-text">暂无定时任务。</span>
          ) : (
            <div className="table-container">
              <table className="table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>执行时间</th>
                    <th>时段</th>
                    <th>场馆运动</th>
                    <th>用户</th>
                    <th>状态</th>
                    <th>最近运行</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {schedules.map((job, index) => {
                    const info = job as Record<string, unknown>;
                    const id = String(info.id ?? `job-${index}`);
                    const hourStr = String(info.hour ?? "00").padStart(2, "0");
                    const minuteStr = String(info.minute ?? "00").padStart(2, "0");
                    const secondStr = String(info.second ?? "00").padStart(2, "0");
                    const presetLabel =
                      info.preset != null && info.preset !== ""
                        ? String(info.preset)
                        : "自定义";
                    const status = String(info.status ?? "unknown");
                    const lastRun =
                      info.last_run != null ? String(info.last_run) : "未运行";
                    const startHoursRaw = Array.isArray(info.start_hours)
                      ? info.start_hours
                      : info.start_hour != null
                        ? [info.start_hour]
                        : [];
                    const startHourLabel = startHoursRaw.length
                      ? startHoursRaw
                          .map((item) => `${Number(item).toString().padStart(2, "0")}:00`)
                          .join(", ")
                      : "-";
                    const displayUsers =
                      Array.isArray(info.target_users) && info.target_users.length
                        ? (info.target_users as unknown[])
                            .map((value) => {
                              const key = String(value).trim();
                              return userLabelMap.get(key) ?? key;
                            })
                            .filter((value, idx, arr) => value && arr.indexOf(value) === idx)
                        : [];
                    const targetUserLabel = displayUsers.length ? displayUsers.join(", ") : "-";

                    return (
                      <tr key={id}>
                        <td>{id}</td>
                        <td>
                          {hourStr}:{minuteStr}:{secondStr}
                        </td>
                        <td>{startHourLabel}</td>
                        <td>{presetLabel}</td>
                        <td>{targetUserLabel}</td>
                        <td>
                          <span className={`chip ${status === "scheduled" ? "chip-info" : "chip-warning"}`}>
                            {status}
                          </span>
                        </td>
                        <td>{lastRun}</td>
                        <td>
                          <button
                            className="button button-secondary"
                            type="button"
                            onClick={() => handleDelete(id)}
                            disabled={loading}
                          >
                            删除
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>

    </>
  );
};

export default SchedulePage;
