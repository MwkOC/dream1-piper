import { useState, type FormEvent } from "react";
import { api } from "../lib/api/client";
import { Button } from "../components/ui/button";

export function Login({ onLogin }: { onLogin: () => void }) {
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    try { await api.login(token); onLogin(); } catch (cause) { setError(String(cause)); }
  }
  return <main className="mx-auto mt-[10vh] grid w-[min(420px,calc(100%-24px))] gap-4 rounded-2xl border border-zinc-300 bg-white p-6 text-zinc-900 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-100"><p className="text-xs font-semibold uppercase tracking-[.25em] text-red-600">Piper · estación local</p><h1 className="text-2xl font-bold">Dream-1 Control</h1><p className="text-sm text-zinc-500">Inicia sesión para habilitar controles.</p><form className="grid gap-4" onSubmit={submit}><label className="grid gap-2">Token de operador<input type="password" value={token} onChange={event => setToken(event.target.value)} autoComplete="current-password" /></label><Button variant="primary">Entrar</Button></form>{error && <p role="alert" className="text-sm text-red-600">{error}</p>}</main>;
}
