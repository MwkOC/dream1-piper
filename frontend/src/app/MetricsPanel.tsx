import { useEffect, useState } from "react";
import { api, type MetricsSnapshot, type StationStatus } from "../lib/api/client";

export function StatusCard({ label, value, accent = "" }: { label: string; value: string; accent?: string }) {
  return <div className="rounded-xl border border-zinc-300 bg-white px-4 py-3 dark:border-zinc-800 dark:bg-zinc-950"><p className="text-xs text-zinc-500">{label}</p><p className={`mt-1 truncate font-semibold ${accent}`}>{value}</p></div>;
}

export function MetricsPanel({ status }: { status: StationStatus }) {
  const [metrics, setMetrics] = useState<MetricsSnapshot | null>(null);
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const update = () => void api.metrics().then(setMetrics).catch(() => undefined);
    update();
    const refresh = window.setInterval(update, 2000);
    const clock = window.setInterval(() => setNow(Date.now()), 1000);
    return () => { window.clearInterval(refresh); window.clearInterval(clock); };
  }, []);

  const trackerActive = status.state === "RUNNING" && status.control_source === "dream";
  const latestTracking = Math.max(
    ...(["left", "right"] as const).map(arm => {
      const value = metrics?.tcp_tracking?.[arm]?.last_recorded_at;
      return value ? Date.parse(value) : 0;
    }),
  );
  const trackingFresh = latestTracking > 0 && now - latestTracking <= 10000;
  const trackerMessage = trackerActive
    ? (trackingFresh ? "Muestreo activo · cada ~3 s" : "Sin muestra reciente · revisa feedback TCP")
    : status.state === "PAUSED"
      ? "Sin objetivos nuevos: operación en pausa"
      : status.control_source === "teleop"
        ? "Teleoperación no genera objetivos Dream"
        : "Esperando una operación Dream";
  return <section className="rounded-2xl border border-zinc-300 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
    <header className="mb-3"><h2 className="font-semibold">Dashboard de métricas</h2><p className="text-xs text-zinc-500">Muestras retenidas · máximo 100000 por acumulador</p></header>
    <div className="grid grid-cols-2 gap-2 text-sm"><SummaryCard label="Dream" value={metrics?.by_source.dream ?? 0} /><SummaryCard label="Teleop" value={metrics?.by_source.teleop ?? 0} /><SummaryCard label="Muestras" value={metrics?.sample_count ?? 0} /><SummaryCard label="Eventos perdidos" value={metrics?.dropped ?? 0} /></div>
    <div className="mt-4 grid gap-2 sm:grid-cols-2">{Object.entries(metrics?.stages ?? {}).map(([stage, summary]) => <LatencyCard key={stage} stage={stage} summary={summary} />)}</div>
    <div className="mt-4"><div className="mb-2 flex items-center justify-between"><h3 className="text-sm font-semibold">Error TCP · teórico contra feedback</h3><span className={`text-xs ${trackerActive && trackingFresh ? "text-green-600" : "text-amber-600"}`}>{trackerMessage}</span></div><div className="grid gap-2 sm:grid-cols-2">{(["left", "right"] as const).map(arm => <TrackingCard key={arm} arm={arm} summary={metrics?.tcp_tracking?.[arm]} now={now} />)}</div></div>
  </section>;
}

function SummaryCard({ label, value }: { label: string; value: number }) {
  return <div className="rounded-lg bg-zinc-100 p-2 dark:bg-zinc-900"><span className="text-xs text-zinc-500">{label}</span><strong className="ml-2 text-sm">{value.toLocaleString()}</strong></div>;
}

function LatencyCard({ stage, summary }: { stage: string; summary: MetricsSnapshot["stages"][string] }) {
  return <article className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800"><div className="mb-2 flex items-center justify-between gap-2"><h4 className="truncate text-xs font-semibold">{stageLabel(stage)}</h4><span className="shrink-0 text-[10px] text-zinc-500">n={summary.sample_count.toLocaleString()}</span></div><div className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs"><Value label="Media" value={summary.mean_ms} suffix="ms" /><Value label="Mediana" value={summary.median_ms} suffix="ms" /><Value label="P95" value={summary.p95_ms} suffix="ms" /><Value label="Último" value={summary.last_ms} suffix="ms" /></div></article>;
}

function TrackingCard({ arm, summary, now }: { arm: "left" | "right"; summary: MetricsSnapshot["tcp_tracking"]["left"] | undefined; now: number }) {
  const last = summary?.last_recorded_at ? Date.parse(summary.last_recorded_at) : NaN;
  const ageSeconds = Number.isFinite(last) ? Math.max(0, Math.floor((now - last) / 1000)) : null;
  return <article className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800"><div className="mb-2 flex items-center justify-between"><h4 className="text-xs font-semibold">Brazo {arm === "left" ? "izquierdo" : "derecho"}</h4><span className="text-[10px] text-zinc-500">{ageSeconds === null ? "sin muestras" : `hace ${ageSeconds} s`}</span></div><div className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs"><Value label="Media" value={summary?.mean_mm} suffix="mm" /><Value label="Mediana" value={summary?.median_mm} suffix="mm" /><Value label="P95" value={summary?.p95_mm} suffix="mm" /><Value label="Último" value={summary?.last_mm} suffix="mm" /><Value label="Orientación" value={summary?.last_orientation_error_deg} suffix="°" /><span className="text-zinc-500">Muestras <b className="ml-1 font-medium text-zinc-900 dark:text-zinc-100">{summary?.sample_count ?? 0}</b></span></div></article>;
}

function Value({ label, value, suffix }: { label: string; value: number | null | undefined; suffix: string }) {
  return <span className="text-zinc-500">{label}<b className="ml-1 font-medium text-zinc-900 dark:text-zinc-100">{value == null ? "—" : `${value.toFixed(1)} ${suffix}`}</b></span>;
}

function stageLabel(stage: string) {
  return stage.replace(/^dream\./, "Dream · ").replaceAll("_", " ");
}
