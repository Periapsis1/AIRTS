import { defineConfig } from "vite";

// The browser client is a static SPA. In dev, Vite serves it with HMR; the
// game server's WebSocket is reached directly (configurable via the in-app
// connect field / VITE_WS_URL). In production, `vite build` emits a static
// bundle served behind the same reverse proxy that fronts the WS endpoint.
export default defineConfig({
  root: ".",
  server: {
    host: true,
    port: 4444,
  },
  preview: {
    host: true,
    port: 4444,
  },
  build: {
    outDir: "dist",
    target: "es2020",
    sourcemap: true,
  },
});
