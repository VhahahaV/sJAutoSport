import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import {
  api,
  type AggregatedSlotEntry,
  type DateAvailabilityStatus,
  type OrderResponse,
  type Preset,
  type UserSummary,
} from "../lib/api";
import PresetSelector from "../components/PresetSelector";
import { fireConfetti, fireFireworks } from "../lib/effects";
import { aggregateAvailableSlots } from "../lib/slotAggregations";
import { czqDebugEnd, czqDebugLog, czqDebugStart } from "../lib/czqDebug";

const WEEKDAY_LABELS = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

const formatDateLabel = (value: string): string => {
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  const weekday = WEEKDAY_LABELS[date.getDay()] ?? "";
  return `${month}-${day} ${weekday}`.trim();
};

const buildSlotLabel = (entry: AggregatedSlotEntry): string => {
  const remainDisplay = entry.total_remain ?? entry.available_count ?? 0;
  return `${entry.start} 余${remainDisplay}`;
};

const OrderPage = () => {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [users, setUsers] = useState<UserSummary[]>([]);
  const [selectedPreset, setSelectedPreset] = useState<number | "">("");
  const [selectedUser, setSelectedUser] = useState<string>("");
  const [dateAvailability, setDateAvailability] = useState<DateAvailabilityStatus[]>([]);
  const [selectedDate, setSelectedDate] = useState<string>("");
  const [slotEntries, setSlotEntries] = useState<AggregatedSlotEntry[]>([]);
  const [selectedSlotKey, setSelectedSlotKey] = useState<string>("");
  const [slotsCache, setSlotsCache] = useState<Record<string, AggregatedSlotEntry[]>>({});
  const [availabilityLoading, setAvailabilityLoading] = useState(false);
  const [slotsLoading, setSlotsLoading] = useState(false);
  const [submitLoading, setSubmitLoading] = useState(false);
  const [result, setResult] = useState<OrderResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

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

  const selectDefaultPreset = useCallback((presetList: Preset[]): number | "" => {
    if (presetList.length === 0) {
      return "";
    }
    const preferred = presetList.find((item) => {
      const venue = item.venue_name || "";
      const field = item.field_type_name || "";
      return /学活|学生中心/.test(venue) && /健身中心|学生健身中心/.test(field);
    });
    return preferred?.index ?? presetList[0].index;
  }, []);

  const loadSlots = useCallback(
    async (presetId: number, dateStr: string, autoSelect: boolean = false) => {
      if (!dateStr) {
        setSlotEntries([]);
        setSelectedSlotKey("");
        return;
      }

      const overallStart = czqDebugStart(`OrderPage.loadSlots preset=${presetId} date=${dateStr}`);
      let requestStart: number | null = null;
      setSlotsLoading(true);
      setError(null);
      setResult(null);
      try {
        requestStart = czqDebugStart(`OrderPage.loadSlots.request preset=${presetId} date=${dateStr}`);
        const response = await api.getImmediateSlots({
          preset: presetId,
          date: dateStr,
          show_full: true,
        });
        if (requestStart !== null) {
          czqDebugEnd(`OrderPage.loadSlots.response preset=${presetId} date=${dateStr}`, requestStart);
          requestStart = null;
        }
        const entries = aggregateAvailableSlots(response.slots || [], response.date);
        setSlotEntries(entries);
        if (autoSelect) {
          const first = entries[0];
          setSelectedSlotKey(first ? first.start : "");
        }
        setSlotsCache((prev) => ({ ...prev, [dateStr]: entries }));
        czqDebugEnd(`OrderPage.loadSlots.complete preset=${presetId} date=${dateStr} entries=${entries.length}`, overallStart);
      } catch (err) {
        setSlotEntries([]);
        if (autoSelect) {
          setSelectedSlotKey("");
        }
        setError((err as Error).message);
        czqDebugLog(`OrderPage.loadSlots.error preset=${presetId} date=${dateStr}`);
        if (requestStart !== null) {
          czqDebugEnd(`OrderPage.loadSlots.response preset=${presetId} date=${dateStr} error`, requestStart);
          requestStart = null;
        }
        czqDebugEnd(`OrderPage.loadSlots.complete preset=${presetId} date=${dateStr} error`, overallStart);
      } finally {
        setSlotsLoading(false);
      }
    },
    [],
  );

  const loadAvailability = useCallback(
    async (presetId: number) => {
      setAvailabilityLoading(true);
      setError(null);
      setResult(null);
      setSlotsCache({});
      const overallStart = czqDebugStart(`OrderPage.loadAvailability preset=${presetId}`);
      let requestStart: number | null = null;
      try {
        requestStart = czqDebugStart(`OrderPage.loadAvailability.request preset=${presetId}`);
        const response = await api.getImmediateAvailability({ preset: presetId, include_slots: true });
        if (requestStart !== null) {
          czqDebugEnd(`OrderPage.loadAvailability.response preset=${presetId}`, requestStart);
          requestStart = null;
        }
        const availableDates = (response.dates || []).filter((entry) => entry.selectable);
        setDateAvailability(availableDates);
        if (availableDates.length === 0) {
          setSelectedDate("");
          setSlotEntries([]);
          setSelectedSlotKey("");
          setError("当前场馆暂无可预订日期，请稍后再试。");
          czqDebugEnd(`OrderPage.loadAvailability.complete preset=${presetId} dates=0`, overallStart);
          return;
        }

        const candidate = response.selected_date && availableDates.some((entry) => entry.date === response.selected_date)
          ? response.selected_date
          : response.default_date && availableDates.some((entry) => entry.date === response.default_date)
            ? response.default_date
            : availableDates[0].date;

        setSelectedDate(candidate);

        let initialEntries = aggregateAvailableSlots(response.slots || [], candidate || "");

        setSlotEntries(initialEntries);
        setSlotsCache((prev) => ({ ...prev, ...(candidate ? { [candidate]: initialEntries } : {}) }));
        setSelectedSlotKey(initialEntries[0] ? initialEntries[0].start : "");

        if ((initialEntries.length === 0) && candidate) {
          await loadSlots(presetId, candidate, true);
        }
        czqDebugEnd(`OrderPage.loadAvailability.complete preset=${presetId} dates=${availableDates.length} initial=${initialEntries.length}`, overallStart);
      } catch (err) {
        setDateAvailability([]);
        setSelectedDate("");
        setSlotEntries([]);
        setSelectedSlotKey("");
        setSlotsCache({});
        setError((err as Error).message);
        czqDebugLog(`OrderPage.loadAvailability.error preset=${presetId}`);
        if (requestStart !== null) {
          czqDebugEnd(`OrderPage.loadAvailability.response preset=${presetId} error`, requestStart);
          requestStart = null;
        }
        czqDebugEnd(`OrderPage.loadAvailability.complete preset=${presetId} error`, overallStart);
      } finally {
        setAvailabilityLoading(false);
      }
    },
    [loadSlots],
  );

  useEffect(() => {
    const load = async () => {
      try {
        const [presetResp, userResp] = await Promise.all([
          api.getPresets(),
          api.listUsers(),
        ]);
        setPresets(presetResp.presets);
        const presetIndex = selectDefaultPreset(presetResp.presets);
        setSelectedPreset(presetIndex);
        setUsers(userResp.users);
      } catch (err) {
        setError((err as Error).message);
      }
    };
    void load();
  }, [selectDefaultPreset]);

  useEffect(() => {
    if (typeof selectedPreset === "number") {
      setError(null);
      void loadAvailability(selectedPreset);
    } else {
      setDateAvailability([]);
      setSelectedDate("");
      setSlotEntries([]);
      setSelectedSlotKey("");
    }
  }, [selectedPreset, loadAvailability]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (typeof selectedPreset !== "number") {
      setError("请选择场馆与运动项目");
      return;
    }
    if (!selectedDate) {
      setError("请选择可预订的日期");
      return;
    }
    if (!selectedSlotKey) {
      setError("请选择可预订的时间段");
      return;
    }

    const targetEntry = slotEntries.find((entry) => entry.start === selectedSlotKey);
    if (!targetEntry) {
      setError("时间段信息缺失，请重新选择");
      czqDebugLog("OrderPage.submit.missing_slot");
      return;
    }
    const startTime = targetEntry.start;
    const endTime = targetEntry.end;
    if (!startTime || !endTime) {
      setError("时间段信息缺失，请重新选择");
      czqDebugLog("OrderPage.submit.invalid_slot");
      return;
    }

    let submitStart: number | null = null;
    try {
      submitStart = czqDebugStart(`OrderPage.submit preset=${selectedPreset} date=${selectedDate}`);
      setSubmitLoading(true);
      setError(null);
      setResult(null);
      const payload = {
        preset: selectedPreset,
        date: selectedDate,
        start_time: startTime,
        end_time: endTime,
        user: selectedUser || undefined,
      };
      const response = await api.createOrder(payload);
      setResult(response);
      if (submitStart !== null) {
        czqDebugEnd(`OrderPage.submit.complete preset=${selectedPreset} success=${response.success}`, submitStart);
      }
      if (response.success) {
        fireConfetti({ origin: { x: 0.75, y: 0.22 }, particleCount: 36 });
        fireFireworks({ bursts: 6 });
      }
    } catch (err) {
      setResult(null);
      setError((err as Error).message);
      czqDebugLog(`OrderPage.submit.error preset=${selectedPreset}`);
      if (submitStart !== null) {
        czqDebugEnd(`OrderPage.submit.complete preset=${selectedPreset} error`, submitStart);
      }
    } finally {
      setSubmitLoading(false);
    }
  };

  const presetSummary = useMemo(() => {
    if (typeof selectedPreset !== "number") {
      return "";
    }
    const preset = presets.find((item) => item.index === selectedPreset);
    if (!preset) {
      return "";
    }
    return `${preset.venue_name} · ${preset.field_type_name}`;
  }, [presets, selectedPreset]);

  return (
    <>
      <div className="content-header">
        <div>
          <h2>立即预订</h2>
          <p className="content-subtitle">使用场馆运动快速下单，可选择指定登录用户。</p>
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
            {presetSummary ? <div className="muted-text">当前选择：{presetSummary}</div> : null}
          </div>

          <div className="form-label form-label--full">
            <span>选择日期</span>
            <div className="toggle-row" role="radiogroup" aria-label="可预订日期">
              {dateAvailability.map((entry) => {
                const isActive = selectedDate === entry.date;
                return (
                  <button
                    key={entry.date}
                    type="button"
                    className={`toggle-button toggle-button--compact ${isActive ? "is-active" : ""}`}
                    onClick={() => {
                      if (availabilityLoading || slotsLoading) return;
                      setSelectedDate(entry.date);
                      const cached = slotsCache[entry.date];
                      if (cached && cached.length > 0) {
                        czqDebugLog(`OrderPage.loadSlots.cache_hit date=${entry.date}`);
                        setSlotEntries(cached);
                        setSelectedSlotKey(cached[0] ? cached[0].start : "");
                      } else if (typeof selectedPreset === "number") {
                        czqDebugLog(`OrderPage.loadSlots.fetch date=${entry.date}`);
                        setSlotEntries([]);
                        setSelectedSlotKey("");
                        void loadSlots(selectedPreset, entry.date, true);
                      }
                    }}
                    disabled={availabilityLoading || slotsLoading}
                  >
                    {formatDateLabel(entry.date)}
                  </button>
                );
              })}
            </div>
            {availabilityLoading ? <div className="muted-text">正在加载日期...</div> : null}
            {!availabilityLoading && dateAvailability.length === 0 ? (
              <div className="muted-text">暂未查询到可预订日期。</div>
            ) : null}
          </div>

          <div className="form-label form-label--full">
            <span>选择时间段</span>
            <div className="toggle-row" role="radiogroup" aria-label="可预订时间段">
              {slotEntries.map((entry) => {
                const key = entry.start;
                const isActive = selectedSlotKey === key;
                return (
                  <button
                    key={key}
                    type="button"
                    className={`toggle-button toggle-button--compact ${isActive ? "is-active" : ""}`}
                    disabled={slotsLoading}
                    onClick={() => {
                      if (slotsLoading) return;
                      setSelectedSlotKey(entry.start);
                    }}
                  >
                    {buildSlotLabel(entry)}
                  </button>
                );
              })}
            </div>
            {slotsLoading ? <div className="muted-text">正在加载时间段...</div> : null}
            {!slotsLoading && selectedDate && slotEntries.length === 0 ? (
              <div className="muted-text">该日期暂时无空余时间段，请尝试其他日期。</div>
            ) : null}
          </div>

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
            <button
              className="button button-primary"
              type="submit"
              disabled={submitLoading || availabilityLoading || slotsLoading || slotEntries.length === 0}
            >
              {submitLoading ? "下单中..." : "提交订单"}
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
          <strong>下单提示</strong>
          <span>{error}</span>
        </div>
      ) : null}

      {result ? (
        <div className="panel">
          <div style={{ fontWeight: 600, marginBottom: "6px" }}>{result.success ? "预订成功" : "预订失败"}</div>
          <div>{result.message}</div>
        </div>
      ) : null}
    </>
  );
};

export default OrderPage;
