import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// Built assets are served by FastAPI at /admin/assets (see app/main.py), and
// the app itself lives under /admin -- base must match so index.html's
// generated asset URLs resolve correctly.
export default defineConfig(({ mode }) => {
  // Third arg "" (not the default "VITE_") loads every var from
  // frontend/.env*, not just VITE_-prefixed ones -- this is vite.config.ts
  // itself (build-time, Node-side), never shipped to the browser, so the
  // usual "only VITE_ vars reach client code" safety reasoning doesn't
  // apply here.
  const env = loadEnv(mode, process.cwd(), "");
  const backendUrl = env.VITE_BACKEND_URL || "http://localhost:8000";

  return {
    base: "/admin/",
    plugins: [react()],
    build: {
      outDir: "dist",
    },
    server: {
      // Defaults to matching `uv run uvicorn app.main:app --reload`'s own
      // default port (see README's "Local development" section). Point
      // this at a different port instead of editing this file: copy
      // frontend/.env.example to frontend/.env and set VITE_BACKEND_URL.
      proxy: {
        "/admin/api": backendUrl,
      },
    },
  };
});
