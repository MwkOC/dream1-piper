import { Button } from "../components/ui/button";
import { useTeleopControl } from "./useTeleopControl";

export function TeleopJog({ arm, generation, enabled, jogSpeed }: { arm: "left" | "right"; generation: number; enabled: boolean; jogSpeed: number }) {
  const control = useTeleopControl(arm, generation, enabled);
  const directions: [string, number[]][] = [["X−", [-jogSpeed, 0, 0]], ["X+", [jogSpeed, 0, 0]], ["Y−", [0, -jogSpeed, 0]], ["Y+", [0, jogSpeed, 0]], ["Z−", [0, 0, -jogSpeed]], ["Z+", [0, 0, jogSpeed]]];
  return <div className="grid gap-3 rounded-xl bg-zinc-100 p-3 dark:bg-zinc-900">
    <p>Jog cartesiano · mantén deadman y pulsa Start para habilitar movimiento.</p>
    <div className="flex flex-wrap gap-2"><Button onClick={() => control.socket ? control.disconnect() : control.connect()}>{control.socket ? "Desconectar mando" : "Conectar mando"}</Button><Button variant={control.deadman ? "danger" : "secondary"} disabled={control.socket?.readyState !== WebSocket.OPEN} onPointerDown={event => { event.preventDefault(); control.setHeld(true); }} onPointerUp={() => control.setHeld(false)} onPointerLeave={() => control.setHeld(false)} onPointerCancel={() => control.setHeld(false)}>{control.deadman ? "Deadman activo" : "Mantener deadman"}</Button></div>
    <div className="flex flex-wrap gap-2">{directions.map(([label, vector]) => <Button key={label} disabled={control.socket?.readyState !== WebSocket.OPEN} {...control.bindJog(vector)}>{label}</Button>)}</div>
    <small>Secuencia: {control.sequence} · {enabled ? "mando habilitado" : "en espera de Arm"}</small>
  </div>;
}
