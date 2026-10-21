// One React codebase, two builds:
//   --mode uxp → dist-uxp/  Premiere Pro UXP plugin (load dist-uxp/manifest.json in UXP Developer Tool)
//   --mode web → dist/      standalone UI served by the Kerf engine at http://127.0.0.1:7878/app/
import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// UXP draws <button> natively and ignores our styles: the UXP build renders them as div.kbtn (src/uxp-jsx-runtime.ts),
// so the CSS `button` selectors are mapped to `.kbtn` (and :disabled to aria-disabled) in the emitted stylesheet.
const uxpButtons = {
  name: "kerf-uxp-buttons",
  enforce: "post" as const,
  generateBundle(_: unknown, bundle: Record<string, { type: string; fileName: string; source?: string | Uint8Array }>) {
    for (const f of Object.values(bundle))
      if (f.type === "asset" && f.fileName.endsWith(".css"))
        f.source = String(f.source).replace(/\bbutton\b(?![-\w])/g, ".kbtn").replace(/:disabled/g, '[aria-disabled="true"]');
  },
};

export default defineConfig(({ mode }) => {
  const uxp = mode === "uxp";
  return {
    plugins: uxp ? [react({ jsxImportSource: "kerf-jsx" }), uxpButtons] : [react()],
    resolve: uxp ? { alias: [{ find: /^kerf-jsx\/jsx(-dev)?-runtime$/, replacement: resolve(import.meta.dirname, "src/uxp-jsx-runtime.ts") }] } : {},
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
