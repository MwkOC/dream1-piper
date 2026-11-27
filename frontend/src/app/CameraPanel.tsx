import { useEffect, useState } from "react";
import type { StationStatus } from "../lib/api/client";

const cameras = [
  { id: "top", label: "Cenital" },
  { id: "left", label: "Muñeca izquierda" },
  { id: "right", label: "Muñeca derecha" },
] as const;

export function CameraPanel({ status }: { status: StationStatus }) {
  const [tick, setTick] = useState(Date.now());
  const [expanded, setExpanded] = useState<string | null>(null);
  useEffect(() => {
    const timer = window.setInterval(() => setTick(Date.now()), 500);
    return () => window.clearInterval(timer);
  }, []);
  return <section className="space-y-3 rounded-2xl border border-zinc-300 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
    <div className="flex items-center justify-between"><div><h2 className="font-semibold">Cámaras en vivo</h2><p className="text-xs text-zinc-500">Últimos frames · sin grabación</p></div><span className="text-xs text-zinc-500">Actualización 0,5 s</span></div>
    <div className="grid gap-3 md:grid-cols-3">{cameras.map(camera => <button key={camera.id} onClick={() => setExpanded(expanded === camera.id ? null : camera.id)} className={`overflow-hidden rounded-xl border text-left ${expanded === camera.id ? "md:col-span-3" : ""} border-zinc-200 bg-zinc-100 dark:border-zinc-800 dark:bg-black`}>
      <img className="aspect-video w-full object-contain" src={`/api/v1/cameras/${camera.id}.jpg?time=${tick}`} alt={camera.label} />
      <span className="flex items-center justify-between p-2 text-sm"><span>{camera.label}</span><span className={status.cameras[camera.id]?.connected ? "text-green-600" : "text-red-500"}>{status.cameras[camera.id]?.connected ? "Conectada" : "Sin señal"}</span></span>
    </button>)}</div>
  </section>;
}
