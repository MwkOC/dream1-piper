import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";
import { Login } from "./Login";
import { OperationPanel } from "./OperationPanel";
import { CameraPanel } from "./CameraPanel";
import { ActivityPanel } from "./ActivityPanel";
import { TaskLibrary } from "./TaskLibrary";
import { HistoryPanel } from "./HistoryPanel";
import { useActivity } from "./useActivity";
import { useStation } from "./useStation";
import { api } from "../lib/api/client";
import { Button } from "../components/ui/button";
import { MetricsPanel, StatusCard } from "./MetricsPanel";

type View = "operation" | "tasks" | "history";
type Theme = "dark" | "light";

export function App() {
  const { status, error, refresh } = useStation();
  const { events, connected } = useActivity();
  const [authenticated, setAuthenticated] = useState(false);
  const [authChecked, setAuthChecked] = useState(false);
  const [view, setView] = useState<View>("operation");
  const [theme, setTheme] = useState<Theme>(() => localStorage.getItem("piper-theme") === "light" ? "light" : "dark");
  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    localStorage.setItem("piper-theme", theme);
  }, [theme]);
  useEffect(() => {
    void api.session().then(() => setAuthenticated(true)).catch(() => undefined).finally(() => setAuthChecked(true));
  }, []);
  if (!authChecked) return <main className="mx-auto mt-24 max-w-sm rounded-2xl border border-zinc-300 bg-white p-6 text-zinc-700 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-200">Conectando con la estación…</main>;
  if (!authenticated) return <Login onLogin={() => setAuthenticated(true)} />;
  const stationIdle = status?.state !== "ARMED" && status?.state !== "RUNNING";
  return <main className="mx-auto grid max-w-[1500px] gap-4 px-4 py-5 text-zinc-900 md:px-7 dark:text-zinc-100">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-300 pb-4 dark:border-zinc-800">
      <div><p className="text-xs font-semibold uppercase tracking-[.25em] text-red-600">Piper · ROS 2 Jazzy</p><h1 className="text-2xl font-bold">Dream-1 Control</h1></div>
      <div className="flex items-center gap-2"><a className="rounded-lg px-3 py-2 text-sm text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-900" href="/api-docs" target="_blank">API</a><Button onClick={() => setTheme(theme === "dark" ? "light" : "dark")} aria-label="Cambiar tema">{theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}{theme === "dark" ? "Claro" : "Oscuro"}</Button><Button onClick={async () => { await api.logout(); setAuthenticated(false); }}>Salir</Button></div>
    </header>
    {error && <div role="alert" className="rounded-xl border border-red-300 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200">API: {error}</div>}
    {status && <>
      <section className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <StatusCard label="Estación" value={status.state} accent={status.state === "FAULT" ? "text-red-600" : status.state === "RUNNING" ? "text-green-600" : ""} />
        <StatusCard label="Modo" value={status.control_source === "dream" ? "DreamLabs" : status.control_source === "teleop" ? "Teleoperación" : "En espera"} />
        <StatusCard label="Worker" value={status.worker_connected ? "Conectado" : "Desconectado"} accent={status.worker_connected ? "text-green-600" : "text-zinc-500"} />
        <StatusCard label="Actividad" value={connected ? "En vivo" : "Reconectando"} accent={connected ? "text-green-600" : "text-amber-600"} />
      </section>
      <nav className="flex gap-2 overflow-x-auto border-b border-zinc-300 dark:border-zinc-800" aria-label="Secciones">
        {([["operation", "Operación"], ["tasks", "Tareas"], ["history", "Historial"]] as const).map(([key, label]) => <button key={key} onClick={() => setView(key)} className={`border-b-2 px-4 py-2 text-sm font-medium ${view === key ? "border-red-600 text-red-700 dark:text-red-400" : "border-transparent text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100"}`}>{label}</button>)}
      </nav>
      {view === "operation" && <div className="grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(340px,1fr)]"><div className="grid content-start gap-4"><CameraPanel status={status} /><OperationPanel status={status} onChange={() => void refresh()} /></div><div className="grid content-start gap-4"><ActivityPanel events={events} connected={connected} /><MetricsPanel status={status} /></div></div>}
      {view === "tasks" && <TaskLibrary disabled={!stationIdle} onSelect={async task => { await api.task(task.prompt, task.task_id); await refresh(); setView("operation"); }} />}
      {view === "history" && <HistoryPanel disabled={!stationIdle} onPurged={() => void refresh()} />}
      {status.last_fault && <div role="alert" className="rounded-xl border border-red-400 bg-red-50 p-3 text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200">Fallo: {status.last_fault}</div>}
    </>}
  </main>;
}
