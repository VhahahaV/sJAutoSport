import { aggregateAvailableSlots } from "./slotAggregations";
const rawApiBase =
  (typeof import.meta !== "undefined" && import.meta.env?.VITE_API_BASE_URL) || "/api";

// Ensure we keep a single slash between base and path to avoid malformed URLs.
const API_BASE = rawApiBase.replace(/\/+$/, "");

export const buildUrl = (path: string) =>
  `${API_BASE}${path.startsWith("/") ? "" : "/"}${path}`;

const extractErrorMessage = (payload: unknown): string | null => {
  if (!payload) return null;
  if (typeof payload === "string") return payload.trim() || null;
  if (Array.isArray(payload)) {
    for (const entry of payload) {
      const message = extractErrorMessage(entry);
      if (message) return message;
    }
    return null;
  }
  if (typeof payload === "object") {
    const record = payload as Record<string, unknown>;
    if (record.error) return extractErrorMessage(record.error);
    if (typeof record.message === "string" && record.message.trim()) {
      return record.message.trim();
    }
    if (typeof record.detail === "string" && record.detail.trim()) {
      return record.detail.trim();
    }
    if (Array.isArray(record.detail)) {
      const messages = record.detail
        .map((item) => extractErrorMessage(item))
        .filter((msg): msg is string => Boolean(msg));
      if (messages.length > 0) {
        return messages.join("; ");
      }
    }
  }
  return null;
};

type FetchOptions = RequestInit & { parseJson?: boolean };

async function request<T>(path: string, options: FetchOptions = {}): Promise<T> {
  const { parseJson = true, headers, ...rest } = options;
  const response = await fetch(buildUrl(path), {
    headers: {
      "Content-Type": "application/json",
      ...(headers || {}),
    },
    ...rest,
  });
  const contentType = response.headers.get("content-type") || "";

  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new Event("session-expired"));
    const text = await response.text();
    let message = text.trim();
    if (!message && contentType.includes("application/json")) {
      try {
        const parsed = JSON.parse(text);
        message = extractErrorMessage(parsed) || "";
      } catch {
        // swallow parsing errors, fall through to default message
      }
    } else if (message.startsWith("{") || message.startsWith("[")) {
      try {
        const parsed = JSON.parse(message);
        message = extractErrorMessage(parsed) || message;
      } catch {
        // ignore JSON parse errors
      }
    }

    throw new Error(message || `Request failed with status ${response.status}`);
  }

  if (!parseJson) {
    // @ts-expect-error - caller expects void
    return undefined;
  }

  if (contentType.includes("application/json")) {
    return (await response.json()) as T;
  }

  const preview = (await response.text()).slice(0, 200).trim();
  const hint = preview ? ` Preview: ${preview}` : "";
  throw new Error(
    `Unexpected response type (${contentType || "unknown"}) from ${path}.${hint}`,
  );
}

export type HealthResponse = {
  status: string;
};

export type LoginFlowResponse = {
  success: boolean;
  message?: string | null;
  captcha_required?: boolean;
  session_id?: string | null;
  captcha_base64?: string | null;
  captcha_mime?: string | null;
  retry?: boolean;
  username?: string | null;
  nickname?: string | null;
  expires_at?: string | null;
};

export type Preset = {
  index: number;
  venue_id: string;
  venue_name: string;
  field_type_id: string;
  field_type_name: string;
  field_type_code?: string | null;
};

export type OrderRecord = {
  pOrderid: string;
  orderstateid: string;
  venuename: string;
  venname: string;
  spaceInfo: string;
  ordercreatement: string;
  orderpaytime?: string;
  scDate?: string;
  countprice: number;
  can_cancel: boolean;
};

export type VenueSummary = {
  name: string;
  id: string;
  address?: string | null;
  phone?: string | null;
};

export type FieldTypeSummary = {
  name: string;
  id: string;
  category?: string | null;
};

export type SlotDetails = {
  slot_id: string;
  start: string;
  end: string;
  price?: number | null;
  available: boolean;
  remain?: number | null;
  capacity?: number | null;
  field_name?: string | null;
  area_name?: string | null;
  sub_site_id?: string | null;
  sign?: string | null;
};

export type SlotAvailability = {
  date: string;
  slot: SlotDetails;
};

export type AggregatedSlotEntry = {
  date: string;
  start: string;
  end: string;
  site_count: number;
  available_count: number;
  total_remain: number | null;
  min_price: number | null;
  max_price: number | null;
};

export type AggregatedSlotsByDay = {
  date: string;
  entries: AggregatedSlotEntry[];
};

export type DateAvailabilityStatus = {
  date: string;
  token?: string | null;
  open: boolean;
  is_all: boolean;
  selectable: boolean;
};

export type ImmediateAvailabilityResponse = {
  resolved: SlotQueryResponse["resolved"];
  dates: DateAvailabilityStatus[];
  default_date?: string | null;
  selected_date?: string | null;
  entries?: AggregatedSlotEntry[];
  slots?: SlotAvailability[];
};

export type ImmediateSlotsResponse = {
  resolved: SlotQueryResponse["resolved"];
  date: string;
  entries: AggregatedSlotEntry[];
  slots: SlotAvailability[];
};

export type SlotQueryResponse = {
  resolved: {
    label: string;
    venue_id: string;
    venue_name?: string | null;
    field_type_id: string;
    field_type_name?: string | null;
    preset?: Preset | null;
  };
  slots: SlotAvailability[];
  aggregated_days?: AggregatedSlotsByDay[];
};

export type UserProfile = {
  create_time?: string | null;
  login_name?: string | null;
  user_name?: string | null;
  phone?: string | null;
  sex?: string | null;
  dept?: string | null;
  code?: string | null;
  class_no?: string | null;
  admin?: boolean | null;
  roles?: string[];
};

export type SlotQueryRequest = {
  preset?: number;
  venue_id?: string;
  field_type_id?: string;
  date?: string;
  start_hour?: number;
  show_full?: boolean;
  target?: Record<string, unknown>;
  all_days?: boolean;
  incremental?: boolean;
};

export type ImmediateAvailabilityRequest = {
  preset?: number;
  venue_id?: string;
  field_type_id?: string;
  target?: Record<string, unknown>;
  date?: string;
  include_slots?: boolean;
};

export type ImmediateSlotsRequest = ImmediateAvailabilityRequest & {
  date: string;
  show_full?: boolean;
  include_slots?: boolean;
};

export type MonitorRequestBody = {
  monitor_id: string;
  preset?: number;
  venue_id?: string;
  field_type_id?: string;
  date?: string;
  start_hour?: number;
  interval_seconds?: number;
  auto_book?: boolean;
  long_running?: boolean;
  target?: Record<string, unknown>;
  preferred_hours?: number[];
  preferred_days?: number[];
  operating_start_hour?: number;
  operating_end_hour?: number;
};

export type OrderRequestBody = {
  preset: number;
  date: string;
  start_time: string;
  end_time?: string;
  target?: Record<string, unknown>;
};

export type SessionState = { sso_available: boolean; verified_at?: string | null; renewed_at?: string | null; login_required?: boolean };
export type Account = SessionState & { username: string | null; nickname: string | null; expires_at: string | null; is_online: boolean };
export type LoginStatusResponse = { success: boolean; account: Account | null; status?: string; message?: string };
export type OrderResponse = { success: boolean; message: string; order_id?: string | null };
export type MonitorInfo = Record<string, unknown>;
export type KeepAliveSummary = { success: boolean; message: string; username: string | null; nickname: string | null; status: "online" | "renewed" | "login_required" | "error" | "session_changed"; sso_available: boolean; checked_at?: string };
export type KeepAliveSettings = { enabled: boolean; interval_minutes: number; last_run?: string; last_result?: KeepAliveSummary; session?: SessionState };
export type DashboardCardConfig = { id: string; preset: number; days: number };
export type DashboardDay = { date: string; status: "available" | "full" | "closed" | "unopened" | "error"; slots: SlotDetails[]; message?: string };
export type DashboardAvailability = { card_id: string; days: DashboardDay[]; updated_at: string };

type Envelope<T> = { ok: boolean; result?: T; error?: { code: string; message?: string; details?: unknown } };
export async function coreCall<T>(operation: string, payload: object = {}): Promise<T> {
  const response = await request<Envelope<T>>(`/core/${operation}`, { method: "POST", body: JSON.stringify(payload) });
  if (response.error) throw new Error(response.error.message || JSON.stringify(response.error.details) || response.error.code);
  if (response.result === undefined) throw new Error("核心未返回结果");
  if (!response.ok && !operation.startsWith("auth.") && !["orders.create", "orders.cancel", "keep-alive.run"].includes(operation)) {
    throw new Error((response.result as { message?: string })?.message || "操作未完成，请刷新后重试");
  }
  return response.result;
}

export type QrLogin = { success: boolean; session_id?: string; status: "connecting" | "waiting" | "confirming" | "success" | "expired" | "error" | "cancelled"; qr_base64?: string; qr_mime?: string; image_version?: number; expires_at?: string; message?: string };

const selection = (payload: ImmediateAvailabilityRequest) => ({ preset: payload.preset, venue_id: payload.venue_id, field_type_id: payload.field_type_id, target: payload.target });

export const api = {
  getHealth: () => request<HealthResponse>("/health"),
  getLoginStatus: () => coreCall<LoginStatusResponse>("auth.status"),
  getAccountInfo: () => coreCall<{ success: boolean; profile: UserProfile | null; message?: string }>("account.info"),
  startLogin: (payload: { username: string; password: string }) => coreCall<LoginFlowResponse>("auth.start", payload),
  submitLoginCode: (payload: { session_id: string; code: string }) => coreCall<LoginFlowResponse>("auth.verify", payload),
  cancelLoginSession: (sessionId: string) => coreCall<{ success: boolean }>("auth.cancel", { session_id: sessionId }),
  startQrLogin: () => coreCall<QrLogin>("auth.qr-start"),
  getQrLogin: (sessionId: string) => coreCall<QrLogin>("auth.qr-status", { session_id: sessionId }),
  cancelQrLogin: (sessionId: string) => coreCall<QrLogin>("auth.qr-cancel", { session_id: sessionId }),
  logout: () => coreCall<{ success: boolean }>("auth.logout"),
  getPresets: async () => ({ presets: await coreCall<Preset[]>("presets.list") }),
  getDashboardCards: () => coreCall<DashboardCardConfig[]>("dashboard.list"),
  addDashboardCard: (payload: { preset: number; days: number }) => coreCall<DashboardCardConfig>("dashboard.add", payload),
  deleteDashboardCard: (cardId: string) => coreCall<{ success: boolean }>("dashboard.delete", { card_id: cardId }),
  getDashboardAvailability: (cardId: string) => coreCall<DashboardAvailability>("dashboard.availability", { card_id: cardId }),
  searchVenues: async (keyword: string, page = 1, size = 20) => ({ venues: await coreCall<VenueSummary[]>("venues.list", { keyword, page, size }) }),
  getFieldTypes: async (venueId: string) => ({ field_types: await coreCall<FieldTypeSummary[]>("venues.fields", { venue_id: venueId }) }),
  querySlots: (payload: SlotQueryRequest) => {
    const { all_days, incremental, ...rest } = payload;
    return coreCall<SlotQueryResponse>("slots.list", { ...rest, all_dates: all_days });
  },
  getImmediateAvailability: async (payload: ImmediateAvailabilityRequest): Promise<ImmediateAvailabilityResponse> => {
    const result = await coreCall<{ resolved: SlotQueryResponse["resolved"]; dates: DateAvailabilityStatus[] }>("dates.list", selection(payload));
    return { ...result, default_date: result.dates[0]?.date, selected_date: payload.date || result.dates[0]?.date };
  },
  getImmediateSlots: async (payload: ImmediateSlotsRequest): Promise<ImmediateSlotsResponse> => {
    const result = await coreCall<SlotQueryResponse>("slots.list", { ...selection(payload), date: payload.date, show_full: payload.show_full });
    return { ...result, date: payload.date, entries: aggregateAvailableSlots(result.slots, payload.date, payload.show_full) };
  },
  createOrder: (payload: OrderRequestBody) => coreCall<OrderResponse>("orders.create", payload),
  getOrders: (page = 1, pageSize = 100) => coreCall<{ success: boolean; orders: OrderRecord[]; total: number; message?: string }>("orders.list", { page_no: page, page_size: pageSize }),
  cancelOrder: (id: string) => coreCall<OrderResponse>("orders.cancel", { order_id: id }),
  listMonitors: () => coreCall<{ success: boolean; monitors: MonitorInfo[] }>("monitors.list"),
  createMonitor: (payload: MonitorRequestBody) => coreCall<{ success: boolean }>("monitors.create", payload),
  pauseMonitor: (id: string) => coreCall<{ success: boolean }>("monitors.pause", { monitor_id: id }),
  resumeMonitor: (id: string) => coreCall<{ success: boolean }>("monitors.resume", { monitor_id: id }),
  deleteMonitor: (id: string) => coreCall<{ success: boolean }>("monitors.delete", { monitor_id: id }),
  getKeepAlive: () => coreCall<KeepAliveSettings>("keep-alive.status"),
  configureKeepAlive: (payload: { enabled: boolean; interval_minutes: number }) => coreCall<KeepAliveSettings>("keep-alive.configure", payload),
  runKeepAlive: () => coreCall<KeepAliveSummary>("keep-alive.run"),
};
