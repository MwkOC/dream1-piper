import { useCallback, useEffect, useState } from "react";
import { api, type StationStatus } from "../lib/api/client";

export function useStation() {
  const [status, setStatus] = useState<StationStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(async () => {
    try {
      setStatus(await api.status());
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }, []);

  useEffect(() => {
    void refresh();
    const events = new EventSource("/api/v1/events", { withCredentials: true });
    for (const eventName of [
      "status", "metric", "camera", "worker", "control", "action", "worker_health",
      "operation.started", "operation.paused", "fault",
    ]) {
      events.addEventListener(eventName, () => void refresh());
    }
    events.onerror = () => void refresh();
    const timer = window.setInterval(() => void refresh(), 1500);
    return () => { events.close(); window.clearInterval(timer); };
  }, [refresh]);

  return { status, error, refresh };
}
