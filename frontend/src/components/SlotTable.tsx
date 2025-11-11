import { useEffect, useMemo, useState } from "react";
import { api, type SlotAvailability as SlotAvailabilityDetail } from "../lib/api";
import { aggregateAvailableSlots } from "../lib/slotAggregations";
import { czqDebugEnd, czqDebugLog, czqDebugStart } from "../lib/czqDebug";

interface SlotTableProps {
  preset: number;
  venueName: string;
  fieldTypeName: string;
  displayName?: string;
}

const formatDate = (value: string): string => {
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  const weekdays = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
  const weekday = weekdays[date.getDay()] ?? "";
  return `${month}-${day} ${weekday}`.trim();
};

const SlotTable = ({ preset, venueName, fieldTypeName, displayName }: SlotTableProps) => {
  const [selectedDate, setSelectedDate] = useState<string>("");
  const [slots, setSlots] = useState<SlotAvailabilityDetail[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadSlots = async () => {
      const overallStart = czqDebugStart(`SlotTable.load preset=${preset}`);
      try {
        setLoading(true);
        setError(null);
        setSlots([]);
        setSelectedDate("");

        const requestStart = czqDebugStart(`SlotTable.request preset=${preset}`);
        const availabilityResp = await api.getImmediateAvailability({ preset, include_slots: true });
        czqDebugEnd(`SlotTable.response preset=${preset}`, requestStart);
        const availableDates = (availabilityResp.dates || []).filter((entry) => entry.selectable);
        if (availableDates.length === 0) {
          setError("暂无可预订日期");
          czqDebugEnd(`SlotTable.complete preset=${preset} dates=0`, overallStart);
          czqDebugEnd(`SlotTable.complete preset=${preset} dates=0`, overallStart);
          return;
        }

        const date = availabilityResp.selected_date && availableDates.some((entry) => entry.date === availabilityResp.selected_date)
          ? availabilityResp.selected_date
          : availabilityResp.default_date && availableDates.some((entry) => entry.date === availabilityResp.default_date)
            ? availabilityResp.default_date
            : availableDates[0].date;

        const initialSlots = (availabilityResp.slots || []).filter((entry) => entry.slot.available);
        if (initialSlots.length > 0) {
          setSlots(initialSlots);
          setSelectedDate(date);
        } else {
          const detailStart = czqDebugStart(`SlotTable.request detail preset=${preset} date=${date}`);
          const slotsResp = await api.getImmediateSlots({ preset, date, show_full: true });
          czqDebugEnd(`SlotTable.response detail preset=${preset} date=${date}`, detailStart);
          const availableSlots = slotsResp.slots.filter((entry) => entry.slot.available);
          setSlots(availableSlots);
          setSelectedDate(date);
          if (availableSlots.length === 0) {
            setError("该日期暂无空余时间段");
          }
        }
        czqDebugEnd(`SlotTable.complete preset=${preset} date=${date}`, overallStart);
      } catch (err) {
        setSlots([]);
        setSelectedDate("");
        setError((err as Error).message);
        czqDebugLog(`SlotTable.error preset=${preset}`);
        czqDebugEnd(`SlotTable.complete preset=${preset} error`, overallStart);
      } finally {
        setLoading(false);
      }
    };
    void loadSlots();
  }, [preset]);

  const title = useMemo(() => displayName ?? `${venueName} / ${fieldTypeName}`, [displayName, venueName, fieldTypeName]);
  const slotSummaries = useMemo(() => aggregateAvailableSlots(slots, selectedDate), [slots, selectedDate]);

  if (loading) {
    return (
      <div className="panel" style={{ minHeight: "100px", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <span className="muted-text">加载中...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="panel">
        <div style={{ fontWeight: 600, marginBottom: "6px" }}>{title}</div>
        <span className="muted-text">{error}</span>
      </div>
    );
  }

  if (!slotSummaries || slotSummaries.length === 0) {
    return (
      <div className="panel">
        <div style={{ fontWeight: 600, marginBottom: "6px" }}>{title}</div>
        <span className="muted-text">暂无可用场次</span>
      </div>
    );
  }

  return (
    <div className="panel">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
        <h4 style={{ margin: 0, fontSize: "14px", fontWeight: 600 }}>{title}</h4>
        {selectedDate ? <span className="muted-text">日期：{formatDate(selectedDate)}</span> : null}
      </div>
      <table className="table">
        <thead>
          <tr>
            <th>开始时间</th>
            <th>余量</th>
            <th>价格</th>
          </tr>
        </thead>
        <tbody>
          {slotSummaries.map((entry) => {
            const remainValue = entry.total_remain ?? entry.available_count ?? 0;
            let priceValue = "-";
            if (entry.min_price != null && entry.max_price != null) {
              priceValue = entry.min_price === entry.max_price
                ? `¥${entry.min_price}`
                : `¥${entry.min_price}~¥${entry.max_price}`;
            } else if (entry.min_price != null) {
              priceValue = `¥${entry.min_price}`;
            } else if (entry.max_price != null) {
              priceValue = `¥${entry.max_price}`;
            }
            return (
              <tr key={`${entry.date}-${entry.start}`}>
                <td>{entry.start}</td>
                <td>{remainValue}</td>
                <td>{priceValue}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};

export default SlotTable;
