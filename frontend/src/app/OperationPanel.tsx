import { useEffect, useState } from "react";
import { api, type StationStatus } from "../lib/api/client";
import { Button } from "../components/ui/button";
import { TeleopJog } from "./TeleopJog";

export function OperationPanel({ status, onChange }: { status: StationStatus; onChange: () => void }) {
  const [source, setSource] = useState<"dream" | "teleop">("dream");
  const [arm, setArm] = useState<"left" | "right">("left");
  const [task, setTask] = useState(status.task);
  const [error, setError] = useState("");
  useEffect(() => setTask(status.task), [status.task]);
  async function mutate(action: string, fields: Record<string, unknown> = {}) {
    try { setError(""); await api.command(action, fields); onChange(); } catch (cause) { setError(String(cause)); }
  }
  async function saveTask() {
    try { await api.task(task); onChange(); } catch (cause) { setError(String(cause)); }
  }
  const disabled = status.state === "DISCONNECTED" || status.state === "FAULT";
  const controlLocked = status.state === "ARMED" || status.state === "RUNNING";
  return <section className="grid gap-4 rounded-2xl border border-zinc-300 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-950"><div><h2 className="font-semibold">Operación</h2><p className="text-xs text-zinc-500">Elige una fuente y ejecuta el ciclo de forma supervisada.</p></div>
    <div className="grid gap-3 sm:grid-cols-2"><label>Fuente<select className="rounded-lg border border-zinc-300 bg-transparent p-2 dark:border-zinc-700" value={source} disabled={controlLocked} onChange={event => setSource(event.target.value as "dream" | "teleop")}><option value="dream">DreamLabs</option><option value="teleop">Teleoperación</option></select></label>{source === "teleop" && <label>Brazo<select className="rounded-lg border border-zinc-300 bg-transparent p-2 dark:border-zinc-700" value={arm} disabled={controlLocked} onChange={event => setArm(event.target.value as "left" | "right")}><option value="left">Izquierdo</option><option value="right">Derecho</option></select></label>}</div>
    {source === "dream" ? <label className="grid gap-2">Instrucción activa<textarea className="min-h-20 rounded-lg border border-zinc-300 bg-transparent p-3 dark:border-zinc-700" value={task} onChange={event => setTask(event.target.value)} /><Button className="justify-self-start" onClick={saveTask}>Aplicar instrucción</Button></label> : <TeleopJog arm={arm} generation={status.control_generation} enabled={status.state === "ARMED" || status.state === "RUNNING"} jogSpeed={status.teleop_limits.jog_speed_m_s} />}
    <div className="flex flex-wrap gap-2 border-t border-zinc-200 pt-3 dark:border-zinc-800"><Button onClick={() => void mutate("validate")} disabled={disabled}>Validar</Button><Button onClick={() => void mutate("arm", { control_source: source, selected_arm: source === "teleop" ? arm : null })} disabled={!status.hardware_validated}>Armar</Button><Button variant="primary" onClick={() => void mutate("start")} disabled={status.state !== "ARMED"}>Iniciar</Button><Button variant="danger" onClick={() => void mutate("pause")}>Pausar</Button><Button onClick={() => window.confirm("Home mueve ambos brazos a la postura configurada. Confirma que el área está despejada.") && void mutate("home")} disabled={!status.hardware_validated || controlLocked}>Home</Button>{status.state === "FAULT" && <Button variant="danger" onClick={() => window.confirm("Confirma que el controlador fue revisado físicamente y que no requiere recuperación manual.") && void mutate("fault/reset")}>Restablecer estación</Button>}</div>{error && <p role="alert" className="text-sm text-red-600">{error}</p>}</section>;
}
