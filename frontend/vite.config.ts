import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built assets are served by FastAPI at /admin/assets (see app/main.py), and
// the app itself lives under /admin -- base must match so index.html's
// generated asset URLs resolve correctly.
export default defineConfig({
  base: "/admin/",
  plugins: [react()],
  build: {
    outDir: "dist",
  },
  server: {
    // Matches `uv run uvicorn app.main:app --reload`'s default port (see
    // README's "Local development" section) -- pass --port 8113 there (and
    // adjust this) if you're pointing at a docker-compose instance instead.
    proxy: {
      "/admin/api": "http://localhost:8000",
    },
  },
});
