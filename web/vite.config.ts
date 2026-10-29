/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Served at the site root by CloudFront (or the UI Lambda); config.json is written next to it by scripts/deploy.sh.
export default defineConfig({
  base: "/",
  plugins: [react()],
  build: { outDir: "dist", sourcemap: false },
  test: { environment: "jsdom", globals: true, setupFiles: ["src/test/setup.ts"] },
});
