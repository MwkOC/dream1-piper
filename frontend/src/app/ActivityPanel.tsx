import { useState } from "react";
import type { ActivityEvent } from "./useActivity";

const labels: Record<string, string> = {
  observation: "Observación Dream", invocation: "Meta / inferencia Dream", action: "Acción aceptada o rechazada",
  "operation.started": "Operación iniciada", "operation.paused": "Operación pausada",
  worker_health: "Worker", metric: "Métrica", fault: "Fallo", status: "Estado", control: "Control",
};

export function ActivityPanel({ events, connected }: { events: ActivityEvent[]; connected: boolean }) {
  const [selected, setSelected] = useState<string | null>(null);
  return <section className="rounded-2xl border border-zinc-300 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
    <div className="mb-3 flex items-center justify-between"><div><h2 className="font-semibold">Actividad en vivo</h2><p className="text-xs text-zinc-500">Dream, teleoperación, resultados y latencia</p></div><span className={`text-xs ${connected ? "text-green-600" : "text-amber-600"}`}>{connected ? "Conectado" : "Reconectando"}</span></div>
    <div className="max-h-80 divide-y divide-zinc-200 overflow-auto dark:divide-zinc-800">{events.length === 0 && <p className="py-5 text-sm text-zinc-500">Aún no hay eventos.</p>}
      {events.map(event => <div key={event.event_id} className="py-2"><button onClick={() => setSelected(selected === event.event_id ? null : event.event_id)} className="flex w-full items-center justify-between gap-3 text-left text-sm"><span className="min-w-0"><b>{labels[event.type] ?? event.type}</b><span className="ml-2 text-zinc-500">{String(event.data.control_source ?? event.data.stage ?? "estación")}</span><span className="ml-2 truncate text-zinc-500">{String(event.data.result ?? event.data.reason ?? "")}</span></span><span className="shrink-0 text-xs text-zinc-500">{new Date(String(event.data.timestamp ?? event.received_at)).toLocaleTimeString()}</span></button>
        {selected === event.event_id && <pre className="mt-2 max-h-52 overflow-auto rounded-lg bg-zinc-100 p-3 text-xs dark:bg-zinc-900">{JSON.stringify(event.data, null, 2)}</pre>}</div>)}
    </div>
  </section>;
}
