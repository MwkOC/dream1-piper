import { useEffect, useRef, useState } from "react";

export function useTeleopSocket() {
  const [socket, setSocket] = useState<WebSocket | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  useEffect(() => { socketRef.current = socket; }, [socket]);
  function connect() {
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    const next = new WebSocket(`${scheme}://${location.host}/api/v1/teleop`);
    next.onclose = () => setSocket(null);
    setSocket(next);
  }
  function disconnect() { socket?.close(); }
  return { socket, socketRef, connect, disconnect };
}
