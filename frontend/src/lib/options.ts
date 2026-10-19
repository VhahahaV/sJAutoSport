export const HOURS_24 = Array.from({ length: 24 }, (_, hour) => hour);
export const BOOKING_HOURS = HOURS_24;
export const DEFAULT_HOURS = BOOKING_HOURS;

export const buildHourOptions = (hours: readonly number[] = DEFAULT_HOURS) =>
  hours.map((hour) => ({
    value: hour,
    label: `${String(hour).padStart(2, "0")}:00`,
  }));

export const buildMinuteOptions = () =>
  Array.from({ length: 60 }, (_, minute) => ({
    value: minute,
    label: String(minute).padStart(2, "0"),
  }));

export const buildSecondOptions = buildMinuteOptions;

export const buildDayOffsetOptions = () =>
  Array.from({ length: 9 }, (_, day) => ({
    value: day,
    label: day === 0 ? "今天" : day === 1 ? "明天" : `+${day}天`,
  }));
