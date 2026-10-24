import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// base "./" keeps the build host-agnostic: Vercel serves it at the domain root and a GitHub Pages
// copy would serve it from a subpath.
export default defineConfig({
  base: "./",
  plugins: [react()],
  build: { chunkSizeWarningLimit: 700 },
});
