import { useEffect, useRef, useState, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import { api, ApiError, type ActivityRecord } from "../lib/api/client";

export type ActivityEvent = ActivityRecord;
export type ActivityConnection = "connecting" | "live" | "reconnecting" | "auth_required";

const EVENT_TYPES = [
  "status", "metric", "camera", "worker", "control", "action", "worker_health",
  "operation.started", "operation.paused", "fault", "observation", "invocation",
];

export function useActivity(onEvent?: (eventType: string) => void) {
  const [latestAction, setLatestAction] = useState<ActivityEvent | null>(null);
  const [latestObservation, setLatestObservation] = useState<ActivityEvent | null>(null);
  const [connection, setConnection] = useState<ActivityConnection>("connecting");
  const onEventRef = useRef(onEvent);
  const authProbeActive = useRef(false);
  const seenEventIds = useRef(new Set<string>());

  useEffect(() => { onEventRef.current = onEvent; }, [onEvent]);

  useEffect(() => {
    const source = new EventSource("/api/v1/events", { withCredentials: true });
    let active = true;
    const handlers = addActivityListeners(source, (type, message) => {
      receiveActivityEvent(type, message, setLatestAction, setLatestObservation, onEventRef, setConnection, seenEventIds);
    });
    source.onopen = () => setConnection("live");
    source.onerror = () => checkStreamConnection(
      () => active,
      authProbeActive,
      setConnection,
    );
    return () => {
      active = false;
      source.onopen = null;
      source.onerror = null;
      handlers.forEach(([type, handler]) => source.removeEventListener(type, handler));
      source.close();
    };
  }, []);
  return { latestAction, latestObservation, connection };
}

function addActivityListeners(source: EventSource, receive: (type: string, event: Event) => void) {
  return EVENT_TYPES.map(type => {
    const handler = (event: Event) => receive(type, event);
    source.addEventListener(type, handler);
    return [type, handler] as const;
  });
}

function receiveActivityEvent(
  type: string,
  message: Event,
  setLatestAction: Dispatch<SetStateAction<ActivityEvent | null>>,
  setLatestObservation: Dispatch<SetStateAction<ActivityEvent | null>>,
  onEventRef: MutableRefObject<((eventType: string) => void) | undefined>,
  setConnection: Dispatch<SetStateAction<ActivityConnection>>,
  seenEventIds: MutableRefObject<Set<string>>,
) {
  try {
    const envelope = JSON.parse((message as MessageEvent<string>).data) as Record<string, unknown>;
    const eventId = String(envelope.event_id ?? crypto.randomUUID());
    if (seenEventIds.current.has(eventId)) return;
    rememberEvent(seenEventIds.current, eventId);
    const event: ActivityEvent = {
      event_id: eventId,
      type,
      data: (envelope.data as Record<string, unknown> | undefined) ?? envelope,
      received_at: new Date().toISOString(),
    };
    if (type === "action") setLatestAction(current => current?.event_id === eventId ? current : event);
    if (type === "observation") setLatestObservation(current => current?.event_id === eventId ? current : event);
    onEventRef.current?.(type);
  } catch {
    setConnection("reconnecting");
  }
}

function rememberEvent(seen: Set<string>, eventId: string) {
  seen.add(eventId);
  if (seen.size > 500) seen.delete(seen.values().next().value as string);
}

function checkStreamConnection(
  isActive: () => boolean,
  authProbeActive: MutableRefObject<boolean>,
  setConnection: Dispatch<SetStateAction<ActivityConnection>>,
) {
  setConnection("reconnecting");
  if (authProbeActive.current) return;
  authProbeActive.current = true;
  void api.session().catch(cause => {
    if (isActive() && cause instanceof ApiError && cause.status === 401) {
      setConnection("auth_required");
    }
  }).finally(() => { authProbeActive.current = false; });
}
