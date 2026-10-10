// Sift's React pages (docs/kb/decisions/adr-018-react-typescript-pages.md).
// One self-contained script, web/dist/sift-ui.js, loaded by web/index.html
// before app.js. It's committed, so the owner's PC needs no Node.js.
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  build: {
    outDir: "../web/dist",
    emptyOutDir: true,
    sourcemap: false,
    lib: { entry: "src/main.tsx", name: "SiftUI", formats: ["iife"], fileName: () => "sift-ui.js" },
  },
  test: { environment: "jsdom", include: ["src/**/*.test.tsx", "src/**/*.test.ts"] },
});
