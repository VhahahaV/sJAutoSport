import type { AggregatedSlotEntry, SlotAvailability } from "./api";

const toNumber = (value: unknown): number | null => {
  if (typeof value === "number" && !Number.isNaN(value)) return value;
  if (typeof value === "string") {
    const parsed = Number(value);
    if (!Number.isNaN(parsed)) {
      return parsed;
    }
  }
  return null;
};

export const aggregateAvailableSlots = (
  slots: SlotAvailability[],
  fallbackDate?: string,
  includeFull = false,
): AggregatedSlotEntry[] => {
  const groups = new Map<string, AggregatedSlotEntry>();

  for (const availability of slots) {
    const { date, slot } = availability;
    if (!slot.available && !includeFull) {
      continue;
    }
    const start = String(slot.start || "");
    if (!start) {
      continue;
    }
    const end = String(slot.end || "");
    const key = `${date || fallbackDate || ""}/${start}/${end}`;
    const remainValue = toNumber(slot.remain);
    if (remainValue !== null && remainValue <= 0 && !includeFull) {
      continue;
    }
    const priceValue = toNumber(slot.price);
    const available = slot.available && (remainValue === null || remainValue > 0);
    const remaining = available ? remainValue : 0;

    const existing = groups.get(key);
    if (existing) {
      existing.site_count += 1;
      existing.available_count += Number(available);
      if (existing.total_remain === null || remaining === null) {
        existing.total_remain = null;
      } else {
        existing.total_remain += remaining;
      }
      if (priceValue !== null) {
        existing.min_price = existing.min_price === null ? priceValue : Math.min(existing.min_price, priceValue);
        existing.max_price = existing.max_price === null ? priceValue : Math.max(existing.max_price, priceValue);
      }
      if (!existing.end && end) {
        existing.end = end;
      }
    } else {
      groups.set(key, {
        date: date || fallbackDate || "",
        start,
        end,
        site_count: 1,
        available_count: Number(available),
        total_remain: remaining,
        min_price: priceValue,
        max_price: priceValue,
      });
    }
  }

  const result = Array.from(groups.values());
  result.sort((a, b) => a.start.localeCompare(b.start));
  return result;
};
