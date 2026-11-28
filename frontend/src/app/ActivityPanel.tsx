import { useEffect, useRef, useState } from "react";
import { api, type ActivityRecord } from "../lib/api/client";
import type { ActivityEvent } from "./useActivity";

const PAGE_SIZE = 20;
const labels: Record<string, string> = {
  observation: "Observación Dream", invocation: "Inferencia Dream", action: "Acción",
  "operation.started": "Operación iniciada", "operation.paused": "Operación pausada",
  worker_health: "Worker", metric: "Métrica", fault: "Fallo", status: "Estado", control: "Control",
};
const fieldLabels: Record<string, string> = {
  control_source: "Fuente", source: "Fuente", stage: "Etapa", result: "Resultado", reason: "Motivo",
  arm: "Brazo", sequence: "Secuencia", duration_ms: "Duración", position_error_mm: "Error TCP",
  orientation_error_deg: "Error de orientación", target_age_ms: "Edad del objetivo",
  task: "Instrucción", checkpoint: "Modelo", state: "Estado", session_id: "Sesión",
  operation_id: "Operación", invocation_id: "Inferencia", recorded_at: "Registrado",
};

type PageData = { items: ActivityRecord[]; total: number; limit: number; offset: number };

export function ActivityPanel({ events, connected }: { events: ActivityEvent[]; connected: boolean }) {
  const [page, setPage] = useState(0);
  const [data, setData] = useState<PageData | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState("");
  const liveEvents = useRef(events);
  const seenLiveIds = useRef(new Set(events.map(event => event.event_id)));
  liveEvents.current = events;

  useEffect(() => {
    let active = true;
    api.activityEvents(PAGE_SIZE, page * PAGE_SIZE).then(result => {
      if (!active) return;
      const live = page === 0 ? liveEvents.current.slice(0, PAGE_SIZE) : [];
      const storedIds = new Set(result.items.map(event => event.event_id));
      const liveOnlyCount = live.filter(event => !storedIds.has(event.event_id)).length;
      const items = mergeEvents(live, result.items).slice(0, PAGE_SIZE);
      setData({ ...result, items, total: result.total + liveOnlyCount });
      setError("");
    }).catch(cause => { if (active) setError(String(cause)); });
    return () => { active = false; };
  }, [page]);

  useEffect(() => {
    const newEvents = events.filter(event => !seenLiveIds.current.has(event.event_id));
    seenLiveIds.current = new Set(events.map(event => event.event_id));
    if (page !== 0 || newEvents.length === 0) return;
    setData(current => {
      if (!current) return current;
      const items = mergeEvents(newEvents, current.items).slice(0, PAGE_SIZE);
      return { ...current, items, total: current.total + newEvents.length };
    });
  }, [events, page]);

  const items = data?.items ?? [];
  const pages = Math.max(1, Math.ceil((data?.total ?? 0) / PAGE_SIZE));
  const selectedEvent = items.find(event => event.event_id === selected);
  return <section className="rounded-2xl border border-zinc-300 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
    <header className="mb-3 flex items-center justify-between gap-3"><div><h2 className="font-semibold">Actividad</h2><p className="text-xs text-zinc-500">Registros recientes · detalle al seleccionar</p></div><span className={`text-xs ${connected ? "text-green-600" : "text-amber-600"}`}>{connected ? "En vivo" : "Reconectando"}</span></header>
    <div className="max-h-80 divide-y divide-zinc-200 overflow-auto dark:divide-zinc-800">
      {items.length === 0 && <p className="py-5 text-sm text-zinc-500">Aún no hay eventos.</p>}
      {items.map(event => <ActivityRow key={event.event_id} event={event} selected={selected === event.event_id} onSelect={() => setSelected(selected === event.event_id ? null : event.event_id)} />)}
    </div>
    {selectedEvent && <EventDetails event={selectedEvent} />}
    {error && <p role="alert" className="mt-2 text-xs text-red-600">No se pudo cargar el historial: {error}</p>}
    <footer className="mt-3 flex items-center justify-between border-t border-zinc-200 pt-3 text-xs dark:border-zinc-800"><span className="text-zinc-500">{data?.total ?? 0} registros · página {page + 1} de {pages}</span><div className="flex gap-2"><button className="rounded border border-zinc-300 px-2 py-1 disabled:opacity-40 dark:border-zinc-700" disabled={page === 0} onClick={() => { setSelected(null); setPage(value => Math.max(0, value - 1)); }}>Anterior</button><button className="rounded border border-zinc-300 px-2 py-1 disabled:opacity-40 dark:border-zinc-700" disabled={page + 1 >= pages} onClick={() => { setSelected(null); setPage(value => value + 1); }}>Siguiente</button></div></footer>
  </section>;
}

function ActivityRow({ event, selected, onSelect }: { event: ActivityRecord; selected: boolean; onSelect: () => void }) {
  const category = labels[event.type] ?? event.type;
  return <button onClick={onSelect} aria-expanded={selected} className="flex w-full items-center justify-between gap-3 py-2 text-left hover:bg-zinc-50 dark:hover:bg-zinc-900/60">
    <span className="min-w-0"><span className="block truncate text-sm font-medium">{category}</span><span className="block truncate text-xs text-zinc-500">{eventSummary(event)}</span></span>
    <time className="shrink-0 text-[11px] text-zinc-500">{formatTime(event.received_at)}</time>
  </button>;
}

function EventDetails({ event }: { event: ActivityRecord }) {
  const fields = Object.entries(fieldLabels).filter(([key]) => event.data[key] !== undefined && event.data[key] !== null);
  return <div className="mt-3 rounded-xl border border-zinc-200 bg-zinc-50 p-3 dark:border-zinc-800 dark:bg-zinc-900/60">
    <p className="mb-2 text-sm font-semibold">{labels[event.type] ?? event.type} · {formatTime(event.received_at)}</p>
    <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-xs">{fields.map(([key, label]) => <div key={key}><dt className="text-zinc-500">{label}</dt><dd className="break-words font-medium">{formatValue(event.data[key], key)}</dd></div>)}</dl>
    <details className="mt-3"><summary className="cursor-pointer text-xs text-zinc-500">Payload técnico</summary><pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-all rounded bg-white p-2 text-[10px] dark:bg-black">{JSON.stringify(event.data, null, 2)}</pre></details>
  </div>;
}

function mergeEvents(first: ActivityRecord[], second: ActivityRecord[]) {
  const merged = new Map<string, ActivityRecord>();
  for (const event of [...first, ...second]) merged.set(event.event_id, event);
  return [...merged.values()].sort((left, right) => Date.parse(right.received_at) - Date.parse(left.received_at));
}

function eventSummary(event: ActivityRecord) {
  const data = event.data;
  if (event.type === "metric" && data.stage === "tcp_tracking_error") {
    const arm = data.arm === "left" ? "izquierdo" : "derecho";
    return data.result === "measured" ? `Brazo ${arm} · ${formatValue(data.position_error_mm, "position_error_mm")}` : `Brazo ${arm} · ${String(data.reason ?? data.result)}`;
  }
  const source = data.control_source ?? data.source;
  const sourceLabel = source ? `${String(source)} · ` : "";
  const outcome = data.result ?? data.reason ?? data.stage ?? data.state ?? data.task;
  return `${sourceLabel}${outcome === undefined ? "Evento de estación" : String(outcome)}`;
}

function formatValue(value: unknown, key: string) {
  if (typeof value === "number") {
    if (key === "duration_ms" || key === "target_age_ms") return `${value.toFixed(1)} ms`;
    if (key === "position_error_mm") return `${value.toFixed(2)} mm`;
    if (key === "orientation_error_deg") return `${value.toFixed(2)}°`;
    return Number.isInteger(value) ? String(value) : value.toFixed(3);
  }
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function formatTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
