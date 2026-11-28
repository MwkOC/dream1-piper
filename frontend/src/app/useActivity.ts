import { useEffect, useState } from "react";
import type { ActivityRecord } from "../lib/api/client";

export type ActivityEvent = ActivityRecord;

export function useActivity() {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    const source = new EventSource("/api/v1/events", { withCredentials: true });
    const types = ["status", "metric", "camera", "worker", "control", "action", "worker_health",
      "operation.started", "operation.paused", "fault", "observation", "invocation"];
    const handlers = types.map(type => {
      const handler = (message: Event) => {
        const data = JSON.parse((message as MessageEvent<string>).data) as Record<string, unknown>;
        setEvents(current => [{
          event_id: String(data.event_id ?? crypto.randomUUID()),
          type,
          data: (data.data as Record<string, unknown> | undefined) ?? data,
          received_at: new Date().toISOString(),
        }, ...current].slice(0, 150));
      };
      source.addEventListener(type, handler);
      return [type, handler] as const;
    });
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    return () => { handlers.forEach(([type, handler]) => source.removeEventListener(type, handler)); source.close(); };
  }, []);
  return { events, connected };
}
