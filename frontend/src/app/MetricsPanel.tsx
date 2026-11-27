import { useEffect, useState } from "react";
import { api } from "../lib/api/client";

export function StatusCard({ label, value, accent = "" }: { label: string; value: string; accent?: string }) {
  return <div className="rounded-xl border border-zinc-300 bg-white px-4 py-3 dark:border-zinc-800 dark:bg-zinc-950"><p className="text-xs text-zinc-500">{label}</p><p className={`mt-1 truncate font-semibold ${accent}`}>{value}</p></div>;
}

export function MetricsPanel() {
  const [metrics, setMetrics] = useState<{ sample_count: number; by_source: Record<string, number>; dropped: number; stages?: Record<string, { last_ms?: number | null; p95_ms?: number | null }> } | null>(null);
  useEffect(() => {
    const update = () => void api.metrics().then(setMetrics).catch(() => undefined);
    update();
    const timer = window.setInterval(update, 2000);
    return () => window.clearInterval(timer);
  }, []);
  return <section className="rounded-2xl border border-zinc-300 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
    <div className="mb-3"><h2 className="font-semibold">Métricas</h2><p className="text-xs text-zinc-500">Ventana activa · fuente y latencia</p></div>
    <div className="grid grid-cols-2 gap-2 text-sm"><Metric label="Dream" value={metrics?.by_source.dream ?? 0} /><Metric label="Teleop" value={metrics?.by_source.teleop ?? 0} /><Metric label="Muestras" value={metrics?.sample_count ?? 0} /><Metric label="Eventos perdidos" value={metrics?.dropped ?? 0} /></div>
    <div className="mt-3 space-y-1 text-xs text-zinc-500">{Object.entries(metrics?.stages ?? {}).map(([stage, values]) => <p key={stage}>{stage}: último {values.last_ms?.toFixed(0) ?? "—"} ms · p95 {values.p95_ms?.toFixed(0) ?? "—"} ms</p>)}</div>
  </section>;
}

function Metric({ label, value }: { label: string; value: number }) {
  return <div className="rounded-lg bg-zinc-100 p-2 dark:bg-zinc-900"><span className="text-zinc-500">{label}</span><strong className="ml-2">{value}</strong></div>;
}
