// One React codebase, two builds:
//   --mode uxp → dist-uxp/  Premiere Pro UXP plugin (load dist-uxp/manifest.json in UXP Developer Tool)
//   --mode web → dist/      standalone UI served by the Kerf engine at http://127.0.0.1:7878/app/
import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const uxp = mode === "uxp";
  return {
    plugins: [react()],
    base: "./",
    publicDir: uxp ? "public" : false,
    define: { "process.env.NODE_ENV": JSON.stringify("production"), __UXP__: uxp },
    build: {
      outDir: uxp ? "dist-uxp" : "dist",
      emptyOutDir: true,
      target: uxp ? "esnext" : "es2020",
      minify: !uxp,
      sourcemap: uxp,
      ...(uxp && {
        // UXP loads plain CommonJS; host modules stay as runtime require() calls (same as Adobe's sample).
        // public/index.html loads index.js as a classic script, like Adobe's UXP samples.
        rolldownOptions: {
          input: resolve(import.meta.dirname, "src/main.tsx"),
          external: ["premierepro", "uxp", "os", "fs"],
          output: {
            format: "cjs",
            entryFileNames: "index.js",
            assetFileNames: (a: { names?: string[] }) => (a.names?.[0]?.endsWith(".css") ? "index.css" : "[name][extname]"),
          },
        },
      }),
    },
  };
});
