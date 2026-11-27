import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const backend = process.env.RSTACK_DEV_API ?? "http://127.0.0.1:8443";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api": { target: backend, ws: true },
      "/api-docs": { target: backend },
      "/openapi.json": { target: backend },
      "/healthz": { target: backend },
      "/readyz": { target: backend },
    },
  },
});
