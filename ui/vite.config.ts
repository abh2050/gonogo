import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// base "./" keeps the build host-agnostic: Vercel serves it at the domain root and a GitHub Pages
// copy would serve it from a subpath.
export default defineConfig({
  base: "./",
  plugins: [react()],
  build: { chunkSizeWarningLimit: 700 },
  // Local development: `uv run uvicorn api.index:app` serves the API on port 8000.
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
});
