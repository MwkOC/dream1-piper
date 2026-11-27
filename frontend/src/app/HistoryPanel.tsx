import { useEffect, useState } from "react";
import { api, type OperationRecord } from "../lib/api/client";
import { Button } from "../components/ui/button";

export function HistoryPanel({ disabled, onPurged }: { disabled: boolean; onPurged: () => void }) {
  const [items, setItems] = useState<OperationRecord[]>([]);
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const refresh = () => api.operations().then(setItems).catch(cause => setError(String(cause)));
  useEffect(() => { void refresh(); }, []);
  async function open(id: string) {
    try { setDetail(await api.operation(id)); setError(""); } catch (cause) { setError(String(cause)); }
  }
  async function purge() {
    if (!window.confirm("Esto eliminará tareas, operaciones, acciones, métricas e historial de forma permanente. ¿Continuar?")) return;
    try { await api.purgeHistory(); setDetail(null); setItems([]); onPurged(); } catch (cause) { setError(String(cause)); }
  }
  return <section className="space-y-3 rounded-2xl border border-zinc-300 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
    <div className="flex items-center justify-between"><div><h2 className="font-semibold">Historial de operaciones</h2><p className="text-xs text-zinc-500">Registro inmutable de tarea, fuente y resultados.</p></div><Button variant="danger" onClick={() => void purge()} disabled={disabled}>Borrar todos los datos</Button></div>
    {items.length === 0 && <p className="text-sm text-zinc-500">No hay operaciones persistidas.</p>}
    <div className="divide-y divide-zinc-200 dark:divide-zinc-800">{items.map(item => <button key={item.operation_id} onClick={() => void open(item.operation_id)} className="flex w-full items-center justify-between gap-3 py-3 text-left"><span><b>{item.control_source === "dream" ? "Dream" : "Teleoperación"}</b><span className="ml-2 text-sm text-zinc-500">{item.task_snapshot || "Sin texto de tarea"}</span></span><span className="shrink-0 text-xs text-zinc-500">{new Date(item.started_at).toLocaleString()} · {item.result ?? "en curso"}</span></button>)}</div>
    {detail && <div className="rounded-xl bg-zinc-100 p-3 dark:bg-zinc-900"><div className="mb-2 flex justify-between"><b>Detalle de operación</b><button onClick={() => setDetail(null)} aria-label="Cerrar detalle">×</button></div><pre className="max-h-72 overflow-auto text-xs">{JSON.stringify(detail, null, 2)}</pre></div>}
    {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
  </section>;
}
