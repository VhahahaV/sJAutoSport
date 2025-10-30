import type { KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent } from "react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

type RangeSelectorProps = {
  min: number;
  max: number;
  step?: number;
  value: [number, number] | null;
  onChange: (next: [number, number] | null) => void;
  formatValue?: (value: number) => string;
  label?: string;
  allowClear?: boolean;
  unit?: string;
};

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max);

const RangeSelector = ({
  min,
  max,
  step = 1,
  value,
  onChange,
  formatValue = (v) => String(v),
  label,
  allowClear = true,
  unit,
}: RangeSelectorProps) => {
  const [range, setRange] = useState<[number, number]>(value ?? [min, max]);
  const trackRef = useRef<HTMLDivElement | null>(null);
  const activeHandleRef = useRef<"start" | "end" | null>(null);
  const rangeRef = useRef<[number, number]>(range);
  const isLimited = useMemo(() => {
    if (!value) {
      return false;
    }
    return !(value[0] === min && value[1] === max);
  }, [value, min, max]);

  useEffect(() => {
    rangeRef.current = range;
  }, [range]);

  useEffect(() => {
    if (!value) {
      const nextRange: [number, number] = [min, max];
      rangeRef.current = nextRange;
      setRange(nextRange);
      return;
    }
    const nextRange: [number, number] = [clamp(value[0], min, max), clamp(value[1], min, max)];
    rangeRef.current = nextRange;
    setRange(nextRange);
  }, [value, min, max]);

  const toPercent = useCallback(
    (val: number) => {
      if (max === min) {
        return 0;
      }
      return ((val - min) / (max - min)) * 100;
    },
    [min, max],
  );

  const snapValue = useCallback(
    (val: number) => {
      const stepped = Math.round((val - min) / step) * step + min;
      return clamp(stepped, min, max);
    },
    [min, max, step],
  );

  const getValueFromClientX = useCallback(
    (clientX: number) => {
      const track = trackRef.current;
      if (!track) {
        return min;
      }
      const rect = track.getBoundingClientRect();
      if (rect.width <= 0) {
        return min;
      }
      const ratio = (clientX - rect.left) / rect.width;
      const clampedRatio = clamp(ratio, 0, 1);
      const raw = min + clampedRatio * (max - min);
      return snapValue(raw);
    },
    [min, max, snapValue],
  );

  const emitChange = useCallback(
    (nextRange: [number, number]) => {
      if (nextRange[0] === min && nextRange[1] === max) {
        onChange(null);
      } else {
        onChange(nextRange);
      }
    },
    [min, max, onChange],
  );

  const updateRange = useCallback(
    (handle: "start" | "end", nextValue: number) => {
      setRange((prev) => {
        let [prevStart, prevEnd] = prev;
        let nextStart = prevStart;
        let nextEnd = prevEnd;
        if (handle === "start") {
          nextStart = Math.min(nextValue, prevEnd);
        } else {
          nextEnd = Math.max(nextValue, prevStart);
        }
        nextStart = clamp(nextStart, min, max);
        nextEnd = clamp(nextEnd, min, max);
        if (nextStart > nextEnd) {
          if (handle === "start") {
            nextStart = nextEnd;
          } else {
            nextEnd = nextStart;
          }
        }
        if (nextStart === prevStart && nextEnd === prevEnd) {
          return prev;
        }
        const nextRange: [number, number] = [nextStart, nextEnd];
        rangeRef.current = nextRange;
        emitChange(nextRange);
        return nextRange;
      });
    },
    [min, max, emitChange],
  );

  const summary = useMemo(() => {
    const [rangeStart, rangeEnd] = range;
    if (rangeStart === min && rangeEnd === max) {
      return "未限制";
    }
    const startLabel = formatValue(rangeStart);
    const endLabel = formatValue(rangeEnd);
    return `${startLabel} ~ ${endLabel}${unit ? ` ${unit}` : ""}`;
  }, [range, min, max, formatValue, unit]);

  const handleClear = () => {
    const resetRange: [number, number] = [min, max];
    rangeRef.current = resetRange;
    setRange(resetRange);
    onChange(null);
  };

  const beginDrag = useCallback(
    (handle: "start" | "end", clientX: number) => {
      const nextValue = getValueFromClientX(clientX);
      activeHandleRef.current = handle;
      updateRange(handle, nextValue);
    },
    [getValueFromClientX, updateRange],
  );

  const handleHandlePointerDown = (handle: "start" | "end") => (event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    beginDrag(handle, event.clientX);
  };

  const handleTrackPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    const pointerValue = getValueFromClientX(event.clientX);
    const [currentStart, currentEnd] = rangeRef.current;
    const distanceToStart = Math.abs(pointerValue - currentStart);
    const distanceToEnd = Math.abs(pointerValue - currentEnd);
    const handle = distanceToStart <= distanceToEnd ? "start" : "end";
    beginDrag(handle, event.clientX);
  };

  useEffect(() => {
    const move = (event: PointerEvent) => {
      const activeHandle = activeHandleRef.current;
      if (!activeHandle) {
        return;
      }
      event.preventDefault();
      const valueFromPointer = getValueFromClientX(event.clientX);
      updateRange(activeHandle, valueFromPointer);
    };

    const end = () => {
      activeHandleRef.current = null;
    };

    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
    };
  }, [getValueFromClientX, updateRange]);

  const handleKeyDown = (handle: "start" | "end") => (event: ReactKeyboardEvent<HTMLDivElement>) => {
    let delta = 0;
    if (event.key === "ArrowLeft" || event.key === "ArrowDown") {
      delta = -step;
    } else if (event.key === "ArrowRight" || event.key === "ArrowUp") {
      delta = step;
    } else if (event.key === "Home") {
      delta = handle === "start" ? min - rangeRef.current[0] : min - rangeRef.current[1];
    } else if (event.key === "End") {
      delta = handle === "start" ? max - rangeRef.current[0] : max - rangeRef.current[1];
    } else {
      return;
    }
    event.preventDefault();
    const current = rangeRef.current;
    const baseValue = handle === "start" ? current[0] : current[1];
    const nextValue = snapValue(baseValue + delta);
    updateRange(handle, nextValue);
  };

  const [rangeStart, rangeEnd] = range;
  const startPercent = toPercent(rangeStart);
  const endPercent = toPercent(rangeEnd);

  return (
    <div className="range-selector">
      <div className="range-selector__header">
        {label ? <span className="range-selector__label">{label}</span> : null}
        <span className="range-selector__summary">{summary}</span>
        {allowClear && isLimited ? (
          <button type="button" className="range-selector__clear" onClick={handleClear}>
            重置
          </button>
        ) : null}
      </div>
      <div className="range-selector__body">
        <div
          className="range-selector__track"
          ref={trackRef}
          onPointerDown={handleTrackPointerDown}
        >
          <div className="range-selector__rail" />
          <div
            className="range-selector__selection"
            style={{ left: `${startPercent}%`, width: `${endPercent - startPercent}%` }}
          />
          <div
            className="range-selector__handle"
            style={{ left: `${startPercent}%` }}
            role="slider"
            tabIndex={0}
            aria-valuemin={min}
            aria-valuemax={rangeEnd}
            aria-valuenow={rangeStart}
            aria-label={label ? `${label} 起始` : "开始时间"}
            onPointerDown={handleHandlePointerDown("start")}
            onKeyDown={handleKeyDown("start")}
          />
          <div
            className="range-selector__handle"
            style={{ left: `${endPercent}%` }}
            role="slider"
            tabIndex={0}
            aria-valuemin={rangeStart}
            aria-valuemax={max}
            aria-valuenow={rangeEnd}
            aria-label={label ? `${label} 结束` : "结束时间"}
            onPointerDown={handleHandlePointerDown("end")}
            onKeyDown={handleKeyDown("end")}
          />
        </div>
        <div className="range-selector__scale">
          <span>{formatValue(min)}</span>
          <span>{formatValue(max)}</span>
        </div>
      </div>
    </div>
  );
};

export default RangeSelector;
