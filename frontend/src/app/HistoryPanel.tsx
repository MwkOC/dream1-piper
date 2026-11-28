import { useEffect, useState } from "react";
import { api, type ActionRecord, type OperationRecord, type Page } from "../lib/api/client";
import { Button } from "../components/ui/button";

const PAGE_SIZE = 50;

export function HistoryPanel({ disabled, onPurged }: { disabled: boolean; onPurged: () => void }) {
  const [items, setItems] = useState<OperationRecord[]>([]);
  const [operation, setOperation] = useState<Record<string, unknown> | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { void api.operations().then(setItems).catch(cause => setError(String(cause))); }, []);
  async function open(id: string) {
    try { setOperation(await api.operation(id)); setSelectedId(id); setError(""); }
    catch (cause) { setError(String(cause)); }
  }
  async function purge() {
    if (!window.confirm("Esto eliminará tareas, operaciones, acciones, métricas e historial de forma permanente. ¿Continuar?")) return;
    try { await api.purgeHistory(); setOperation(null); setSelectedId(null); setItems([]); onPurged(); }
    catch (cause) { setError(String(cause)); }
  }
  return <section className="space-y-3 rounded-2xl border border-zinc-300 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
    <header className="flex items-center justify-between"><div><h2 className="font-semibold">Historial de operaciones</h2><p className="text-xs text-zinc-500">Tareas, fuentes, resultados y muestras de acción paginadas.</p></div><Button variant="danger" onClick={() => void purge()} disabled={disabled}>Borrar todos los datos</Button></header>
    {items.length === 0 && <p className="text-sm text-zinc-500">No hay operaciones persistidas.</p>}
    <OperationList items={items} selectedId={selectedId} onOpen={id => void open(id)} />
    {operation && selectedId && <ActionHistory operation={operation} operationId={selectedId} />}
    {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
  </section>;
}

function OperationList({ items, selectedId, onOpen }: { items: OperationRecord[]; selectedId: string | null; onOpen: (id: string) => void }) {
  return <div className="divide-y divide-zinc-200 dark:divide-zinc-800">{items.map(item => <button key={item.operation_id} onClick={() => onOpen(item.operation_id)} className={`flex w-full items-center justify-between gap-3 py-3 text-left ${selectedId === item.operation_id ? "text-red-600" : ""}`}><span><b>{item.control_source === "dream" ? "Dream" : "Teleoperación"}</b><span className="ml-2 text-sm text-zinc-500">{item.task_snapshot || "Sin texto de tarea"}</span></span><span className="shrink-0 text-xs text-zinc-500">{new Date(item.started_at).toLocaleString()} · {item.result ?? "en curso"}</span></button>)}</div>;
}

function ActionHistory({ operation, operationId }: { operation: Record<string, unknown>; operationId: string }) {
  const [page, setPage] = useState<Page<ActionRecord> | null>(null);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<ActionRecord | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    setSelected(null);
    void api.operationActions(operationId, PAGE_SIZE, offset).then(setPage).catch(cause => setError(String(cause)));
  }, [operationId, offset]);
  const maxOffset = Math.max(0, (page?.total ?? 0) - PAGE_SIZE);
  return <div className="space-y-3 rounded-xl bg-zinc-100 p-3 dark:bg-zinc-900">
    <div><h3 className="font-semibold">{String(operation.task_snapshot ?? "Operación")}</h3><p className="text-xs text-zinc-500">{String(operation.control_source)} · {String(operation.result ?? "en curso")} · {String(operation.action_count ?? page?.total ?? 0)} acciones</p></div>
    <ActionRows items={page?.items ?? []} selected={selected?.action_id ?? null} onSelect={setSelected} />
    {selected && <ActionDetail action={selected} />}
    {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
    <div className="flex items-center justify-between text-xs text-zinc-500"><span>{page ? `${page.total ? offset + 1 : 0}–${Math.min(offset + PAGE_SIZE, page.total)} de ${page.total}` : "Cargando acciones…"}</span><span className="flex gap-2"><Button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Más recientes</Button><Button disabled={offset >= maxOffset} onClick={() => setOffset(offset + PAGE_SIZE)}>Anteriores</Button></span></div>
  </div>;
}

function ActionRows({ items, selected, onSelect }: { items: ActionRecord[]; selected: string | null; onSelect: (item: ActionRecord) => void }) {
  if (!items.length) return <p className="text-sm text-zinc-500">Esta operación no tiene acciones.</p>;
  return <div className="max-h-80 divide-y divide-zinc-300 overflow-auto dark:divide-zinc-700">{items.map(item => <button key={item.action_id} onClick={() => onSelect(item)} className={`flex w-full items-center justify-between gap-3 py-2 text-left text-sm ${selected === item.action_id ? "text-red-600" : ""}`}><span>#{item.sequence ?? "—"} · {item.result} · {String(item.details.observation_id ?? "obs —")}</span><span className="text-xs text-zinc-500">{new Date(item.created_at).toLocaleTimeString()}</span></button>)}</div>;
}

function ActionDetail({ action }: { action: ActionRecord }) {
  return <div className="grid gap-2 md:grid-cols-2"><ValueBlock title="Propuesta" value={action.proposed.named ?? action.proposed.values ?? action.proposed} /><ValueBlock title="Aplicado" value={action.applied.named ?? action.applied.values ?? action.applied} /><ValueBlock title="Correlación worker" value={action.details} /><ValueBlock title="Feedback ROS" value={action.feedback} /></div>;
}

function ValueBlock({ title, value }: { title: string; value: unknown }) {
  return <details className="rounded-lg border border-zinc-300 p-2 dark:border-zinc-700"><summary className="cursor-pointer text-xs font-medium">{title}</summary><pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-all text-[11px] text-zinc-500">{JSON.stringify(value, null, 2) ?? "—"}</pre></details>;
}
