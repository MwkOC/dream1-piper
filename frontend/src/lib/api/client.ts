import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type StationStatus = components["schemas"]["StatusResponse"];
export type RunState = components["schemas"]["RunState"];
export type ControlSource = components["schemas"]["ControlSource"];
type OperationCommand = components["schemas"]["OperationCommand"];

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

const http = createClient<paths>({
  baseUrl: "",
  fetch: request => fetch(request, { credentials: "include" }),
});

async function unwrap<T>(result: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await result;
  if (!response.ok) {
    const detail = typeof error === "object" && error !== null && "detail" in error
      ? String(error.detail)
      : response.statusText;
    throw new ApiError(detail || `HTTP ${response.status}`, response.status);
  }
  return data as T;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(body.detail ?? `HTTP ${response.status}`, response.status);
  return body as T;
}

export type TaskRecord = {
  task_id: string; name: string; prompt: string; created_at: string; updated_at: string; enabled: boolean;
};
export type OperationRecord = {
  operation_id: string; task_id: string | null; task_snapshot: string; control_source: string;
  selected_arm: string | null; started_at: string; ended_at: string | null; result: string | null;
};
export type ActionRecord = {
  action_id: string; operation_id: string; invocation_id: string | null; control_source: string;
  arm: string | null; sequence: number | null; result: string; created_at: string;
  proposed: Record<string, unknown>; applied: Record<string, unknown>; feedback: Record<string, unknown>;
  details: Record<string, unknown>;
};
export type Page<T> = { items: T[]; total: number; limit: number; offset: number };
export type ActivityRecord = {
  event_id: string;
  type: string;
  data: Record<string, unknown>;
  received_at: string;
};
export type MetricSummary = {
  sample_count: number;
  mean_ms?: number | null;
  median_ms?: number | null;
  p95_ms?: number | null;
  last_ms?: number | null;
};
export type TrackingSummary = {
  sample_count: number;
  mean_mm?: number | null;
  median_mm?: number | null;
  p95_mm?: number | null;
  last_mm?: number | null;
  last_orientation_error_deg?: number | null;
  last_target_age_ms?: number | null;
  last_recorded_at?: string | null;
};
export type MetricsSnapshot = {
  sample_count: number;
  by_source: Record<string, number>;
  dropped: number;
  stages: Record<string, MetricSummary>;
  tcp_tracking: Record<"left" | "right", TrackingSummary>;
};

function operation(): OperationCommand {
  return { request_id: crypto.randomUUID() };
}

export const api = {
  status: () => unwrap(http.GET("/api/v1/status")),
  login: (operator_token: string) => unwrap(http.POST("/api/v1/auth/session", { body: { operator_token } })),
  session: () => unwrap(http.GET("/api/v1/auth/session")),
  logout: () => unwrap(http.DELETE("/api/v1/auth/session")),
  task: (task: string, task_id: string | null = null) => request("/api/v1/task", {
    method: "PUT", body: JSON.stringify({ task, task_id }),
  }),
  tasks: () => request<TaskRecord[]>("/api/v1/tasks"),
  createTask: (name: string, prompt: string) => request<TaskRecord>("/api/v1/tasks", {
    method: "POST", body: JSON.stringify({ name, prompt }),
  }),
  updateTask: (taskId: string, name: string, prompt: string) => request<TaskRecord>(`/api/v1/tasks/${taskId}`, {
    method: "PATCH", body: JSON.stringify({ name, prompt }),
  }),
  deleteTask: (taskId: string) => request<{ deleted: boolean }>(`/api/v1/tasks/${taskId}`, { method: "DELETE" }),
  operations: (offset = 0) => request<OperationRecord[]>(`/api/v1/operations?limit=50&offset=${offset}`),
  activityEvents: (limit = 20, offset = 0) => request<{
    items: ActivityRecord[]; total: number; limit: number; offset: number;
  }>(`/api/v1/events/history?limit=${limit}&offset=${offset}`),
  operation: (id: string) => request<Record<string, unknown>>(`/api/v1/operations/${id}`),
  operationActions: (id: string, limit = 50, offset = 0) => request<Page<ActionRecord>>(
    `/api/v1/operations/${id}/actions?limit=${limit}&offset=${offset}`,
  ),
  purgeHistory: () => request<{ deleted: boolean }>("/api/v1/history", {
    method: "DELETE", body: JSON.stringify({ confirmation: "DELETE ALL DATA" }),
  }),
  command: (name: string, fields: Record<string, unknown> = {}) => {
    if (name === "arm") {
      const body = {
        ...operation(),
        control_source: fields.control_source as "dream" | "teleop",
        selected_arm: fields.selected_arm as "left" | "right" | null,
      };
      return unwrap(http.POST("/api/v1/arm", { body }));
    }
    const body = operation();
    switch (name) {
      case "validate": return unwrap(http.POST("/api/v1/validate", { body }));
      case "start": return unwrap(http.POST("/api/v1/start", { body }));
      case "pause": return unwrap(http.POST("/api/v1/pause", { body }));
      case "home": return unwrap(http.POST("/api/v1/home", { body }));
      case "fault/reset": return request("/api/v1/fault/reset", { method: "POST", body: JSON.stringify(body) });
      default: return Promise.reject(new Error(`Unknown station command: ${name}`));
    }
  },
  metrics: () => fetch("/api/v1/metrics", { credentials: "include" }).then(response => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json() as Promise<MetricsSnapshot>;
  }),
};
