import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The browser only ever talks to this origin. /api, /telemetry and /health
// are proxied to the FastAPI backend inside the sandbox — relative URLs
// everywhere (works behind the preview proxy, no CORS/host hardcoding).
export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    // The sandbox proxies previews under a dynamic host; allow it.
    allowedHosts: true,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      "/telemetry": { target: "http://localhost:8000", changeOrigin: true },
      "/health": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
