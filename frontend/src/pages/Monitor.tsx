import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  api,
  type MonitorInfo,
  type MonitorRequestBody,
  type Preset,
  type UserSummary,
} from "../lib/api";
import { BOOKING_HOURS } from "../lib/options";
import PresetSelector from "../components/PresetSelector";
import RangeSelector from "../components/RangeSelector";

const MAX_SLOT_PREVIEW = 5;
const DAY_RANGE = { min: 0, max: 8 } as const;
const HOUR_RANGE = {
  min: BOOKING_HOURS[0],
  max: BOOKING_HOURS[BOOKING_HOURS.length - 1],
} as const;
const OPERATING_RANGE = { min: 0, max: 24 } as const;
const DEFAULT_OPERATING_WINDOW: [number, number] = [9, 18];

const createMonitorId = () => `monitor-${Date.now().toString(36).slice(-6)}`;

const buildRangeValues = (
  range: [number, number] | null,
  { min, max }: { min: number; max: number },
): number[] | undefined => {
  if (!range) {
    return undefined;
  }
  const start = Math.min(range[0], range[1]);
  const end = Math.max(range[0], range[1]);
  if (start <= min && end >= max) {
    return undefined;
  }
  const values: number[] = [];
  for (let value = start; value <= end; value += 1) {
    values.push(value);
  }
  return values;
};

const formatHourValue = (value: number) => `${value.toString().padStart(2, "0")}:00`;

const formatDayValue = (value: number) => {
  if (value <= 0) return "今天";
  if (value === 1) return "明天";
  return `+${value}天`;
};
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

  const [monitorId, setMonitorId] = useState(createMonitorId());
  const [presetIndex, setPresetIndex] = useState<number | "">("");
  const [intervalMinutes, setIntervalMinutes] = useState(3);
  const [autoBook, setAutoBook] = useState(true);  // 默认打开
  const [longRunning, setLongRunning] = useState(false);
  const [requireAllUsersSuccess, setRequireAllUsersSuccess] = useState(false);
  const [includeAllTargets, setIncludeAllTargets] = useState(true);
  const [selectedTargetUsers, setSelectedTargetUsers] = useState<string[]>([]);
  const [preferredHourRange, setPreferredHourRange] = useState<[number, number] | null>(null);
  const [preferredDayRange, setPreferredDayRange] = useState<[number, number] | null>([0, 0]);
  const [operatingHourRange, setOperatingHourRange] =
    useState<[number, number] | null>(DEFAULT_OPERATING_WINDOW);
  const [deleteAllLoading, setDeleteAllLoading] = useState(false);
  const [selectedSport, setSelectedSport] = useState<string>("");

  const userOptions = useMemo<UserOption[]>(
    () =>
      users.map((user, index) => {
        const id = (user.nickname || user.username || `user-${index}`).trim();
        const nickname = user.nickname?.trim();
        const username = user.username?.trim();
        const compactUsername =
          username && username.includes("@") ? username.split("@", 1)[0] : username;
        const label = nickname || compactUsername || `用户 ${index + 1}`;
        const description =
          username && nickname
            ? username
            : username && compactUsername !== username
              ? username
              : undefined;
        return { id, label, description };
      }),
    [users],
  );

  const userLabelMap = useMemo(() => {
    const mapping = new Map<string, string>();
    users.forEach((user, index) => {
      const nickname = user.nickname?.trim();
      const username = user.username?.trim();
      const compact = username && username.includes("@") ? username.split("@", 1)[0] : username;
      const fallback = `用户 ${index + 1}`;
      const label = nickname || compact || username || fallback;
      if (nickname) {
        mapping.set(nickname, nickname);
      }
      if (username) {
        mapping.set(username, label);
      }
      if (compact && compact !== username) {
        mapping.set(compact, compact);
      }
      if (user.key) {
        mapping.set(user.key, label);
      }
    });
    return mapping;
  }, [users]);

  const sportOptions = useMemo(() => {
    // 只保留两个批量监控选项：健身房、羽毛球
    const flags = {
      gym: false,
      badminton: false,
    };

    presets.forEach((preset) => {
      const name = (preset.field_type_name || "").toLowerCase();
      const venue = (preset.venue_name || "").toLowerCase();

      // 识别"健身房"类：包含"健身"关键字，或学生中心健身房等变体
      if (
        name.includes("健身") ||
        name.includes("fitness") ||
        venue.includes("健身")
      ) {
        flags.gym = true;
      }

      // 识别"羽毛球"类
      if (name.includes("羽毛球") || name.includes("badminton")) {
        flags.badminton = true;
      }
    });

    const options: string[] = [];
    if (flags.gym) options.push("健身房");
    if (flags.badminton) options.push("羽毛球");
    return options;
  }, [presets]);

  const matchedSportPresets = useMemo(() => {
    if (!selectedSport) return [];
    const keyword = selectedSport.trim().toLowerCase();

    // "健身房"按钮：只匹配学生中心、子衿街、霍英东这三个场馆的健身房
    if (keyword === "健身房") {
      // 匹配关键词：学生中心、子衿街、霍英东
      const allowedKeywords = ["学生中心", "子衿街", "霍英东"];
      return presets.filter((preset) => {
        const name = (preset.field_type_name || "").toLowerCase();
        const venue = (preset.venue_name || "").toLowerCase();
        const isGym = name.includes("健身") || name.includes("fitness") || venue.includes("健身");
        // 检查场馆名称是否包含任一允许的关键词
        const isAllowedVenue = allowedKeywords.some((keyword) => venue.includes(keyword.toLowerCase()));
        return isGym && isAllowedVenue;
      });
    }

    // "羽毛球"按钮：只匹配霍英东、气膜这两个场馆的羽毛球
    if (keyword === "羽毛球") {
      const allowedVenues = ["霍英东", "气膜"];
      return presets.filter((preset) => {
        const name = (preset.field_type_name || "").toLowerCase();
        const isBadminton = name.includes("羽毛球") || name.includes("badminton");
        const venue = (preset.venue_name || "").toLowerCase();
        const isAllowedVenue = allowedVenues.some((allowed) => venue.includes(allowed.toLowerCase()));
        return isBadminton && isAllowedVenue;
      });
    }

    // 兜底逻辑（理论上不会走到）
    return presets.filter((preset) =>
      (preset.field_type_name || "").toLowerCase().includes(keyword),
    );
  }, [presets, selectedSport]);

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
    setMonitorId(createMonitorId());
    setIntervalMinutes(3);
    setAutoBook(true);
    setLongRunning(false);
    setRequireAllUsersSuccess(false);
    setIncludeAllTargets(true);
    setSelectedTargetUsers([]);
    setPreferredHourRange(null);
    setPreferredDayRange([0, 0]);
    setOperatingHourRange(DEFAULT_OPERATING_WINDOW);
    setSelectedSport("");
  };

  const toggleTargetUser = (userId: string) => {
    setIncludeAllTargets(false);
    setSelectedTargetUsers((prev) =>
      prev.includes(userId)
        ? prev.filter((item) => item !== userId)
        : [...prev, userId]
    );
  };

  const slugify = (value: string) =>
    value
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "preset";

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
      const preferredHoursPayload = buildRangeValues(preferredHourRange, HOUR_RANGE);
      const preferredDaysPayload = buildRangeValues(preferredDayRange, DAY_RANGE);

      const basePayload: MonitorRequestBody = {
        monitor_id: monitorId.trim(),
        preset: presetIndex ? Number(presetIndex) : undefined,
        interval_seconds: intervalMinutes * 60,
        auto_book: autoBook,
        long_running: longRunning,
        require_all_users_success: requireAllUsersSuccess,
        target_users: targetUsersPayload,
        preferred_hours: preferredHoursPayload,
        preferred_days: preferredDaysPayload,
      };

      if (operatingHourRange) {
        const [rawStart, rawEnd] = operatingHourRange;
        const operatingStart = Math.min(rawStart, rawEnd);
        const operatingEnd = Math.max(rawStart, rawEnd);
        // 始终发送 operating_start_hour 和 operating_end_hour，包括 0:00-24:00 的情况
        basePayload.operating_start_hour = operatingStart;
        basePayload.operating_end_hour = operatingEnd;
      }

      const presetTarget = typeof presetIndex === "number"
        ? presets.find((item) => item.index === Number(presetIndex))
        : undefined;

      if (selectedSport && matchedSportPresets.length === 0) {
        setError(`未找到包含「${selectedSport}」的场馆项目`);
        return;
      }

      const targets = matchedSportPresets.length > 0 ? matchedSportPresets : (presetTarget ? [presetTarget] : []);

      if (targets.length === 0) {
        setError("请选择场馆运动或运动类型");
        return;
      }

      const trimmedId = monitorId.trim();
      const creationResults = await Promise.allSettled(
        targets.map(async (target) => {
          const venueSlug = slugify(target.venue_name || `venue-${target.index}`);
          const sportSlug = slugify(target.field_type_name || target.field_type_id || "");
          const suffixParts = [venueSlug, `preset${target.index}`];
          if (sportSlug) {
            suffixParts.push(sportSlug);
          }
          const suffix = suffixParts.join("-");
          const monitorKey = targets.length === 1 ? trimmedId : `${trimmedId}-${suffix}`;
          const payload: MonitorRequestBody = { ...basePayload, monitor_id: monitorKey, preset: target.index };
          await api.createMonitor(payload);
          return { id: monitorKey, venue: target.venue_name };
        }),
      );

      const succeeded = creationResults
        .filter((entry): entry is PromiseFulfilledResult<{ id: string; venue: string }> => entry.status === "fulfilled")
        .map((entry) => entry.value);
      const failed = creationResults.filter((entry) => entry.status === "rejected");

      if (succeeded.length > 0) {
        const venues = succeeded.map((item) => item.venue || item.id).join(", ");
        setMessage(`监控任务已创建：${venues}`);
      }
      if (failed.length > 0) {
        setError(`部分任务创建失败：${failed.length} 项`);
      }

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
      .map((value) => formatHourValue(Number(value)))
      .join(", ");
  };

  const formatDayList = (days: unknown): string => {
    if (!Array.isArray(days) || days.length === 0) {
      return "-";
    }
    return (days as number[])
      .map((day) => formatDayValue(Number(day)))
      .join(", ");
  };

  const formatOperatingWindow = (startRaw: unknown, endRaw: unknown): string => {
    const start = Number(startRaw ?? OPERATING_RANGE.min);
    const end = Number(endRaw ?? OPERATING_RANGE.max);
    const normalizedStart = Number.isFinite(start) ? Math.max(OPERATING_RANGE.min, Math.min(OPERATING_RANGE.max, start)) : OPERATING_RANGE.min;
    const normalizedEnd = Number.isFinite(end) ? Math.max(OPERATING_RANGE.min, Math.min(OPERATING_RANGE.max, end)) : OPERATING_RANGE.max;
    if (normalizedStart <= OPERATING_RANGE.min && normalizedEnd >= OPERATING_RANGE.max) {
      return "全天";
    }
    if (normalizedStart === normalizedEnd) {
      return "全天";
    }
    return `${formatHourValue(normalizedStart)} ~ ${formatHourValue(normalizedEnd)}`;
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
            <span>场馆运动</span>
            <PresetSelector
              presets={presets}
              value={presetIndex}
              onChange={(nextPreset) => setPresetIndex(nextPreset)}
              onClear={() => setPresetIndex("")}
            />
          </div>

          <div className="form-label form-label--full">
            <span>选择运动类型（可选，批量监控）</span>
            <div className="toggle-group toggle-group--wrap">
              <button
                type="button"
                className={`toggle-button ${selectedSport ? "" : "is-active"}`}
                onClick={() => setSelectedSport("")}
              >
                不限运动
              </button>
              {sportOptions.map((sport) => {
                const isActive = selectedSport === sport;
                return (
                  <button
                    key={sport}
                    type="button"
                    className={`toggle-button ${isActive ? "is-active" : ""}`}
                    onClick={() => setSelectedSport(sport)}
                  >
                    {sport}
                  </button>
                );
              })}
            </div>
            {selectedSport ? (
              <span className="muted-text">
                将为所有包含「{selectedSport}」的场馆创建监控任务
              </span>
            ) : (
              <span className="muted-text">默认仅创建上方选择的单个场馆监控</span>
            )}
          </div>

          <div className="form-label form-label--full">
            <RangeSelector
              min={HOUR_RANGE.min}
              max={HOUR_RANGE.max}
              value={preferredHourRange}
              onChange={setPreferredHourRange}
              label="优先时间段"
              formatValue={formatHourValue}
            />
            <span className="muted-text">拖动滑块以限制尝试的起始时间段，不选择时尝试所有可用时段。</span>
          </div>

          <div className="form-label form-label--full">
            <RangeSelector
              min={DAY_RANGE.min}
              max={DAY_RANGE.max}
              value={preferredDayRange}
              onChange={setPreferredDayRange}
              label="优先天数"
              formatValue={formatDayValue}
            />
            <span className="muted-text">0 = 今天，1 = 明天，以此类推；留空时监控所有可预约日期。</span>
          </div>

          <fieldset className="fieldset" style={{ gridColumn: "1 / -1" }}>
            <legend>指定用户</legend>
            <div className="toggle-group toggle-group--wrap">
              <button
                type="button"
                className={`toggle-button ${includeAllTargets ? "is-active" : ""}`}
                onClick={() => {
                  setIncludeAllTargets(true);
                  setSelectedTargetUsers([]);
                }}
              >
                所有用户
              </button>
              {userOptions.map((user) => {
                const isActive = !includeAllTargets && selectedTargetUsers.includes(user.id);
                return (
                  <button
                    key={user.id}
                    type="button"
                    className={`toggle-button ${isActive ? "is-active" : ""}`}
                    onClick={() => toggleTargetUser(user.id)}
                    title={user.description || undefined}
                  >
                    {user.label}
                  </button>
                );
              })}
            </div>
            {!includeAllTargets && selectedTargetUsers.length === 0 ? (
              <span className="muted-text">未选择账号时，将按默认顺序尝试所有可用账号</span>
            ) : null}
          </fieldset>

          <div className="form-label">
            <span>监控间隔（分钟）</span>
            <div className="toggle-group">
              {[1, 3, 5, 10, 15, 25, 30, 60].map((option) => {
                const isActive = intervalMinutes === option;
                return (
                  <button
                    key={`interval-${option}`}
                    type="button"
                    className={`toggle-button ${isActive ? "is-active" : ""}`}
                    onClick={() => setIntervalMinutes(option)}
                  >
                    {option}分钟
                  </button>
                );
              })}
            </div>
          </div>

          <div className="form-label form-label--full">
            <RangeSelector
              min={OPERATING_RANGE.min}
              max={OPERATING_RANGE.max}
              value={operatingHourRange}
              onChange={setOperatingHourRange}
              label="每日运行时段"
              formatValue={formatHourValue}
              unit=""
            />
            <span className="muted-text">限定每日自动监控的时间段；保持 00:00 ~ 24:00 表示全天运行。</span>
          </div>

          <div className="panel" style={{ gridColumn: "1 / -1", border: "2px solid var(--cm-yellow)", background: "#fff5d9", padding: "16px" }}>
            <label style={{ display: "flex", alignItems: "center", gap: "12px", fontWeight: "600", fontSize: "16px" }}>
              <input
                type="checkbox"
                checked={autoBook}
                onChange={(event) => setAutoBook(event.target.checked)}
                style={{ width: "20px", height: "20px" }}
              />
              <span style={{ color: "#705021" }}>🤖 自动预订 - 发现可用场次时自动下单</span>
            </label>
            {autoBook && (
              <label style={{ display: "flex", alignItems: "center", gap: "12px", marginTop: "12px", fontSize: "14px" }}>
                <input
                  type="checkbox"
                  checked={requireAllUsersSuccess}
                  onChange={(event) => setRequireAllUsersSuccess(event.target.checked)}
                  style={{ width: "18px", height: "18px" }}
                />
                <span style={{ color: "var(--cm-link)" }}>
                  ✓ 要求所有用户都成功 - 所有指定账号都在同一场馆抢到场次才算完成，并自动限制开始时间相差不超过 1 小时
                </span>
              </label>
            )}
          </div>

          <div
            className="panel"
            style={{
              gridColumn: "1 / -1",
              border: "1px solid #c8e7d9",
              background: "#e7f7ee",
              padding: "16px",
            }}
          >
            <label style={{ display: "flex", alignItems: "center", gap: "12px", fontWeight: 600 }}>
              <input
                type="checkbox"
                checked={longRunning}
                onChange={(event) => setLongRunning(event.target.checked)}
                style={{ width: "20px", height: "20px" }}
              />
              <span style={{ color: "var(--cm-success)" }}>♾️ 长期监控 - 成功抢到票后仍持续监控优先天数窗口</span>
            </label>
            <p className="muted-text" style={{ marginTop: "8px" }}>
              启用后任务不会进入完成状态，而是每天追踪「今天~明天」这样的滑动窗口，并避免为同一账号重复下单。
            </p>
          </div>

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
        <div className="panel" style={{ border: "1px solid var(--cm-border)", background: "var(--cm-surface)" }}>
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
            <span style={{ color: "var(--cm-muted)" }}>暂无监控任务。</span>
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
                const longRunningFlag = Boolean(info.long_running ?? info.longRunning);
                const lastCycleCompletedRaw =
                  (info.last_cycle_completed_at as string) || (info.lastCycleCompletedAt as string) || "";
                const lastCycleLabel = lastCycleCompletedRaw ? formatDateTime(lastCycleCompletedRaw) : "未完成";
                const targetUserList = Array.isArray(info.target_users) ? (info.target_users as string[]) : [];
                const displayTargetUsers = targetUserList
                  .map((identifier) => {
                    const key = String(identifier).trim();
                    return userLabelMap.get(key) ?? key;
                  })
                  .filter((value, idx, array) => value && array.indexOf(value) === idx);
                const parsedSlots = toSlotPreviewList(info.found_slots);
                const slotPreview = formatSlotPreview(parsedSlots);
                const operatingStartHour = Number(
                  info.operating_start_hour ?? info.operatingStartHour ?? OPERATING_RANGE.min,
                );
                const operatingEndHour = Number(
                  info.operating_end_hour ?? info.operatingEndHour ?? OPERATING_RANGE.max,
                );
                const operatingWindowLabel = formatOperatingWindow(operatingStartHour, operatingEndHour);
                const nextWindowStartRaw = (info.next_window_start as string) || (info.nextWindowStart as string) || "";
                const nextWindowStartLabel = nextWindowStartRaw ? formatDateTime(nextWindowStartRaw) : "-";
                const windowActive = Boolean(info.window_active ?? info.windowActive ?? true);

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
                          className="text-button"
                          type="button"
                          onClick={() => handleDelete(monitorKey)}
                          disabled={loading}
                        >
                          终止任务
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
                        <strong>场馆运动：</strong>
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
                        <strong>长期任务：</strong>
                        {longRunningFlag ? "是" : "否"}
                      </div>
                      <div>
                        <strong>最后检查：</strong>
                        {lastCheck}
                      </div>
                      <div>
                        <strong>上次完成：</strong>
                        {lastCycleLabel}
                      </div>
                      <div>
                        <strong>每日时段：</strong>
                        {operatingWindowLabel}
                      </div>
                      <div>
                        <strong>当前窗口：</strong>
                        {windowActive ? "进行中" : "暂停中"}
                      </div>
                      <div>
                        <strong>下次开启：</strong>
                        {nextWindowStartLabel}
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
                        {displayTargetUsers.length ? displayTargetUsers.join(", ") : "全部"}
                      </div>
                      {slotPreview.length > 0 ? (
                        <div style={{ gridColumn: "1 / -1" }}>
                          <strong>最新可用：</strong>
                          <div className="monitor-card-slots">
                            {slotPreview.map((line, idx) => (
                              <span key={`${monitorKey}-slot-${idx}`} style={{ color: "var(--cm-muted)" }}>
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
