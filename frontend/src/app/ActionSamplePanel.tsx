import type { ActivityRecord } from "../lib/api/client";

type ActionPayload = ActivityRecord["data"];

export function ActionSamplePanel({ action }: { action: ActivityRecord | null }) {
  const data = action?.data as ActionPayload | undefined;
  const proposed = objectField(data, "proposed");
  const applied = objectField(data, "applied");
  const details = objectField(data, "details");
  return <section className="space-y-3 rounded-2xl border border-zinc-300 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
    <header className="flex items-start justify-between gap-2"><div><h2 className="font-semibold">Última muestra de movimiento</h2><p className="text-xs text-zinc-500">Comando worker → estación → ROS</p></div><span className={data?.result === "rejected" ? "text-xs text-red-600" : "text-xs text-green-600"}>{String(data?.result ?? "Esperando acción")}</span></header>
    {data ? <div className="space-y-2 text-sm">
      <p className="text-zinc-600 dark:text-zinc-300">Secuencia <b>{String(data.sequence ?? "—")}</b> · Acción <code className="text-xs">{String(data.action_id ?? "—")}</code></p>
      <p className="text-xs text-zinc-500">Observación asociada: {String(details.observation_id ?? "—")} · Recibida {new Date(action!.received_at).toLocaleTimeString()}</p>
      {data.reason != null && <p className="rounded-lg bg-red-50 p-2 text-red-700 dark:bg-red-950/40 dark:text-red-300">{String(data.reason)}</p>}
      <ValueSummary title="Propuesta" value={proposed.named ?? proposed.values} />
      <ValueSummary title="Aplicado" value={applied.named ?? applied.values} />
      {Object.keys(objectField(data, "feedback")).length > 0 && <ValueSummary title="Feedback ROS" value={objectField(data, "feedback")} />}
    </div> : <p className="py-5 text-sm text-zinc-500">La estación aún no ha recibido una trama de acción.</p>}
  </section>;
}

function ValueSummary({ title, value }: { title: string; value: unknown }) {
  return <details className="rounded-lg border border-zinc-200 p-2 dark:border-zinc-800"><summary className="cursor-pointer text-xs font-medium">{title}</summary><pre className="mt-2 max-h-36 overflow-auto whitespace-pre-wrap break-all text-[11px] text-zinc-500">{formatValue(value)}</pre></details>;
}

function objectField(source: ActionPayload | undefined, key: string): Record<string, unknown> {
  const value = source?.[key];
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function formatValue(value: unknown) {
  return value == null ? "—" : typeof value === "string" ? value : JSON.stringify(value, null, 2);
}
