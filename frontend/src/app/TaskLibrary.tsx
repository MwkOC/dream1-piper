import { useEffect, useState } from "react";
import { api, type TaskRecord } from "../lib/api/client";
import { Button } from "../components/ui/button";

export function TaskLibrary({ onSelect, disabled }: { onSelect: (task: TaskRecord) => Promise<void>; disabled: boolean }) {
  const [items, setItems] = useState<TaskRecord[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [error, setError] = useState("");
  const refresh = () => api.tasks().then(setItems).catch(cause => setError(String(cause)));
  useEffect(() => { void refresh(); }, []);
  function begin(item?: TaskRecord) {
    setEditing(item?.task_id ?? "new"); setName(item?.name ?? ""); setPrompt(item?.prompt ?? ""); setError("");
  }
  async function save() {
    try {
      if (!name.trim() || !prompt.trim()) throw new Error("Completa el nombre y la instrucción.");
      if (editing === "new") await api.createTask(name.trim(), prompt.trim());
      else if (editing) await api.updateTask(editing, name.trim(), prompt.trim());
      setEditing(null); await refresh();
    } catch (cause) { setError(String(cause)); }
  }
  async function remove(item: TaskRecord) {
    if (!window.confirm(`¿Eliminar la tarea “${item.name}”? Las operaciones históricas conservan su texto.`)) return;
    try { await api.deleteTask(item.task_id); await refresh(); } catch (cause) { setError(String(cause)); }
  }
  async function select(item: TaskRecord) {
    try { await onSelect(item); setError(""); }
    catch (cause) { setError(String(cause)); }
  }
  return <section className="space-y-3 rounded-2xl border border-zinc-300 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
    <div className="flex items-center justify-between"><div><h2 className="font-semibold">Biblioteca de tareas</h2><p className="text-xs text-zinc-500">Selecciona una instrucción o administra tus tareas guardadas.</p></div><Button onClick={() => begin()} disabled={disabled}>Nueva</Button></div>
    {editing && <div className="grid gap-2 rounded-xl border border-zinc-200 p-3 dark:border-zinc-800"><input aria-label="Nombre de tarea" placeholder="Nombre" value={name} onChange={event => setName(event.target.value)} /><textarea aria-label="Instrucción de Dream" placeholder="Instrucción para Dream" value={prompt} onChange={event => setPrompt(event.target.value)} className="min-h-20 rounded-lg border border-zinc-300 bg-transparent p-2 dark:border-zinc-700" /><div className="flex gap-2"><Button variant="primary" onClick={() => void save()}>Guardar</Button><Button onClick={() => setEditing(null)}>Cancelar</Button></div></div>}
    <div className="space-y-2">{items.length === 0 && <p className="text-sm text-zinc-500">No hay tareas guardadas.</p>}{items.map(item => <article key={item.task_id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-zinc-200 p-3 dark:border-zinc-800"><div className="min-w-0 flex-1"><h3 className="font-medium">{item.name}</h3><p className="line-clamp-2 text-sm text-zinc-500">{item.prompt}</p></div><div className="flex gap-2"><Button variant="primary" onClick={() => void select(item)} disabled={disabled}>Usar</Button><Button onClick={() => begin(item)} disabled={disabled}>Editar</Button><Button variant="danger" onClick={() => void remove(item)} disabled={disabled}>Eliminar</Button></div></article>)}</div>
    {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
  </section>;
}
