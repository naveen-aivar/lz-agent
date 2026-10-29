/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Served by CloudFront at /v2/ next to the classic UI at /. config.json is the classic UI's, at the root.
export default defineConfig({
  base: "/v2/",
  plugins: [react()],
  build: { outDir: "dist", sourcemap: false },
  test: { environment: "jsdom", globals: true, setupFiles: ["src/test/setup.ts"] },
});
