const rawApiBase =
  (typeof import.meta !== "undefined" && import.meta.env?.VITE_API_BASE_URL) || "/api";

// Ensure we keep a single slash between base and path to avoid malformed URLs.
const API_BASE = rawApiBase.replace(/\/+$/, "");

const buildUrl = (path: string) =>
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

export type LoginStatusResponse = {
  success: boolean;
  active_user: string | null;
  users: Array<{
    key: string;
    username: string | null;
    nickname: string | null;
    expires_at: string | null;
    is_active: boolean;
  }>;
};

export type LoginFlowResponse = {
  success: boolean;
  message?: string | null;
  captcha_required?: boolean;
  session_id?: string | null;
  captcha_image?: string | null;
  captcha_mime?: string | null;
  retry?: boolean;
  username?: string | null;
  nickname?: string | null;
  expires_at?: string | null;
};

export type KeepAliveSummary = {
  username: string | null;
  nickname: string | null;
  success: boolean;
  message: string;
};

export type KeepAliveJob = {
  job_id: string;
  name: string;
  status: string;
  interval_minutes: number;
  created_at: string;
  started_at: string | null;
  pid: number | null;
};

export type JobSummary = {
  job_id: string;
  name: string;
  job_type: string;
  status: string;
  created_at: string;
  started_at: string | null;
  stopped_at: string | null;
  pid: number | null;
};

export type Preset = {
  index: number;
  venue_id: string;
  venue_name: string;
  field_type_id: string;
  field_type_name: string;
  field_type_code?: string | null;
};

export type UserSummary = {
  key?: string | null;
  nickname?: string | null;
  username?: string | null;
  expires_at?: string | null;
  is_active?: boolean;
  password_masked?: string | null;
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
  cancelOrder: boolean;
  name: string;
  userId: string;
};

export type VenueSummary = {
  id: string;
  name: string;
  address?: string | null;
  phone?: string | null;
};

export type FieldTypeSummary = {
  id: string;
  name: string;
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

export type OrderResponse = {
  success: boolean;
  message: string;
  order_id?: string | null;
};

export type MonitorInfo = Record<string, unknown>;
export type ScheduleInfo = Record<string, unknown>;
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

export type UserInfoRecord = {
  key: string | null;
  username: string | null;
  nickname: string | null;
  is_active: boolean;
  success: boolean;
  message?: string | null;
  profile: UserProfile | null;
  raw: unknown;
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

export type OrderRequestBody = {
  preset: number;
  date: string;
  start_time: string;
  user?: string;
  target?: Record<string, unknown>;
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
  require_all_users_success?: boolean;
  target?: Record<string, unknown>;
  target_users?: string[];
  exclude_users?: string[];
  preferred_hours?: number[];
  preferred_days?: number[];
  operating_start_hour?: number;
  operating_end_hour?: number;
};

export type ScheduleRequestBody = {
  job_id: string;
  hour: number;
  minute?: number;
  second?: number;
  preset?: number;
  venue_id?: string;
  field_type_id?: string;
  date?: string;
  start_hour?: number;
  start_hours?: number[];
  require_all_users_success?: boolean;
  target?: Record<string, unknown>;
  target_users?: string[];
  exclude_users?: string[];
};

export const api = {
  // System & jobs
  getHealth: () => request<HealthResponse>("/system/health"),
  getLoginStatus: () => request<LoginStatusResponse>("/system/status/login"),
  getUserInfos: () => request<{ users: UserInfoRecord[] }>("/system/users/info"),
  getOrders: (page: number = 1, pageSize: number = 100) =>
    request<{
      success: boolean;
      orders: OrderRecord[];
      total: number;
      message?: string;
      grouped?: Record<
        string,
        {
          userId: string;
          name: string;
          orders: OrderRecord[];
        }
      >;
      summary?: Array<{
        userId: string;
        name: string;
        count: number;
        error?: string;
      }>;
    }>(`/system/orders?page_no=${page}&page_size=${pageSize}`),
  startLogin: (payload: {
    username?: string;
    password?: string;
    nickname?: string;
    user_id?: string;
  }) =>
    request<LoginFlowResponse>("/auth/login/start", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  submitLoginCode: (payload: { session_id: string; code: string }) =>
    request<LoginFlowResponse>("/auth/login/verify", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  cancelLoginSession: (sessionId: string) =>
    request<{ success: boolean; message?: string }>("/auth/login/cancel", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId }),
    }),
  listJobs: (jobType?: string) => {
    const query = jobType ? `?job_type=${jobType}` : "";
    return request<JobSummary[]>(`/jobs${query}`);
  },

  // Keep-alive
  runKeepAlive: (user?: string) =>
    request<KeepAliveSummary[]>("/keep-alive/run", {
      method: "POST",
      body: JSON.stringify({ user }),
    }),
  listKeepAliveJobs: () => request<KeepAliveJob[]>("/keep-alive/jobs"),
  createKeepAliveJob: (payload: {
    name: string;
    interval_minutes: number;
    auto_start?: boolean;
  }) =>
    request<KeepAliveJob>("/keep-alive/jobs", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteKeepAliveJob: (jobId: string) =>
    request<void>(`/keep-alive/jobs/${jobId}`, {
      method: "DELETE",
      parseJson: false,
    }),

  // Booking reference data
  getPresets: () => request<{ presets: Preset[] }>("/booking/presets"),
  listUsers: () => request<{ users: UserSummary[] }>("/booking/users"),
  searchVenues: (keyword: string, page = 1, size = 20) =>
    request<{ venues: VenueSummary[] }>(
      `/booking/venues?keyword=${encodeURIComponent(keyword)}&page=${page}&size=${size}`,
    ),
  getFieldTypes: (venueId: string) =>
    request<{ field_types: FieldTypeSummary[] }>(`/booking/venues/${venueId}/field-types`),

  // Booking actions
  querySlots: (payload: SlotQueryRequest) =>
    request<SlotQueryResponse>("/booking/slots", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  createOrder: (payload: OrderRequestBody) =>
    request<OrderResponse>("/booking/order", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  // Monitor management
  listMonitors: () => request<{ success: boolean; monitors?: MonitorInfo[]; monitor_info?: MonitorInfo }>(
    "/booking/monitors",
  ),
  createMonitor: (payload: MonitorRequestBody) =>
    request<Record<string, unknown>>("/booking/monitors", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteMonitor: (monitorId: string) =>
    request<{ success: boolean; message: string }>(`/booking/monitors/${monitorId}`, {
      method: "DELETE",
    }),
  pauseMonitor: (monitorId: string) =>
    request<Record<string, unknown>>(`/booking/monitors/${monitorId}/pause`, {
      method: "POST",
    }),
  resumeMonitor: (monitorId: string) =>
    request<Record<string, unknown>>(`/booking/monitors/${monitorId}/resume`, {
      method: "POST",
    }),

  // Job management
  deleteAllJobs: (jobType?: string, force?: boolean) => {
    const params = new URLSearchParams();
    if (jobType) params.append("job_type", jobType);
    if (force) params.append("force", "true");
    const query = params.toString() ? `?${params.toString()}` : "";
    return request<{ success: boolean; message: string; deleted_count: number }>(
      `/jobs/all${query}`,
      { method: "DELETE" }
    );
  },

  // Schedule management
  listSchedules: () =>
    request<{ success: boolean; jobs: ScheduleInfo[] }>("/booking/schedules"),
  createSchedule: (payload: ScheduleRequestBody) =>
    request<Record<string, unknown>>("/booking/schedules", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteSchedule: (jobId: string) =>
    request<Record<string, unknown>>(`/booking/schedules/${jobId}`, {
      method: "DELETE",
    }),
  cancelOrder: (orderId: string, user?: string) =>
    request<{ success: boolean; message: string; steps?: unknown[] }>(
      `/system/orders/${orderId}/cancel`,
      {
        method: "POST",
        body: JSON.stringify({ user }),
      },
    ),
};
