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
    const timer = window.setInterval(() => void refresh(), 1500);
    return () => window.clearInterval(timer);
  }, [refresh]);

  return { status, error, refresh };
}
