import { useEffect, useState } from "react";
import { api, type SlotQueryResponse } from "../lib/api";

interface SlotTableProps {
  preset: number;
  venueName: string;
  fieldTypeName: string;
}

const SlotTable = ({ preset, venueName, fieldTypeName }: SlotTableProps) => {
  const [slots, setSlots] = useState<SlotQueryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadSlots = async () => {
      try {
        setLoading(true);
        const response = await api.querySlots({
          preset,
          date: "0",
          show_full: false,
        });
        setSlots(response);
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setLoading(false);
      }
    };
    void loadSlots();
  }, [preset]);

  if (loading) {
    return (
      <div className="panel" style={{ minHeight: "100px", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <span className="muted-text">加载中...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="panel notice notice-error">
        <strong>加载失败</strong>
        <span>{error}</span>
      </div>
    );
  }

  if (!slots || slots.slots.length === 0) {
    return (
      <div className="panel">
        <div style={{ fontWeight: 600, marginBottom: "6px" }}>
          {venueName} / {fieldTypeName}
        </div>
        <span className="muted-text">暂无可用场次</span>
      </div>
    );
  }

  // 只显示今天有可用场次的时间段
  const availableSlots = slots.slots.filter((slot) => slot.slot.available);

  if (availableSlots.length === 0) {
    return (
      <div className="panel">
        <div style={{ fontWeight: 600, marginBottom: "6px" }}>
          {venueName} / {fieldTypeName}
        </div>
        <span className="muted-text">暂无可用场次</span>
      </div>
    );
  }

  return (
    <div className="panel">
      <h4 style={{ marginBottom: "12px", fontSize: "14px", fontWeight: 600 }}>
        {venueName} / {fieldTypeName}
      </h4>
      <table className="table">
        <thead>
          <tr>
            <th>时间</th>
            <th>场地</th>
            <th>余量</th>
            <th>价格</th>
          </tr>
        </thead>
        <tbody>
          {availableSlots.map((slot, index) => (
            <tr key={index}>
              <td>{slot.slot.start}-{slot.slot.end}</td>
              <td>{slot.slot.field_name || "-"}</td>
              <td>{slot.slot.remain || "-"}</td>
              <td>¥{slot.slot.price || "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

export default SlotTable;

