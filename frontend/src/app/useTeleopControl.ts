import { useEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { useTeleopSocket } from "./useTeleopSocket";

export function useTeleopControl(arm: "left" | "right", generation: number, enabled: boolean) {
  const { socket, socketRef, connect, disconnect } = useTeleopSocket();
  const [deadman, setDeadman] = useState(false);
  const [sequence, setSequence] = useState(0);
  const deadmanRef = useRef(false);
  const directionRef = useRef([0, 0, 0]);
  const sequenceRef = useRef(0);
  const enabledRef = useRef(enabled);
  useEffect(() => { enabledRef.current = enabled; }, [enabled]);
  useEffect(() => { if (!socket && deadmanRef.current) setHeld(false); }, [socket]);
  function send(deadmanActive = deadmanRef.current) {
    const activeSocket = socketRef.current;
    if (activeSocket?.readyState !== WebSocket.OPEN || (deadmanActive && !enabledRef.current)) return;
    const next = sequenceRef.current + 1;
    sequenceRef.current = next;
    setSequence(next);
    activeSocket.send(JSON.stringify({
      type: "heartbeat", sequence: next, control_generation: generation, arm,
      deadman: deadmanActive,
      linear: deadmanActive ? directionRef.current : [0, 0, 0], angular: [0, 0, 0],
    }));
  }
  useEffect(() => {
    if (!deadman || !socket) return;
    const timer = window.setInterval(() => send(true), 50);
    return () => window.clearInterval(timer);
  }, [deadman, socket, generation, arm]);
  function setHeld(active: boolean) {
    deadmanRef.current = active;
    setDeadman(active);
    if (!active) { directionRef.current = [0, 0, 0]; send(false); }
  }
  function bindJog(vector: number[]) {
    return {
      onPointerDown: (event: ReactPointerEvent) => {
        event.preventDefault(); directionRef.current = vector;
        if (!deadmanRef.current) setHeld(true);
      },
      onPointerUp: () => { directionRef.current = [0, 0, 0]; },
      onPointerLeave: () => { directionRef.current = [0, 0, 0]; },
      onPointerCancel: () => { directionRef.current = [0, 0, 0]; },
    };
  }
  return { socket, deadman, sequence, setHeld, bindJog, connect, disconnect };
}
