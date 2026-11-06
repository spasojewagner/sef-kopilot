import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    // Honour the `@/*` alias from tsconfig.json.
    tsconfigPaths: true,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
    // What a test stubs with vi.stubGlobal or vi.stubEnv is put back after it.
    unstubGlobals: true,
    unstubEnvs: true,
    server: {
      deps: {
        // next-intl imports `next/navigation` without the extension Node's ESM loader asks
        // for; transformed by Vite, the import is resolved as the application resolves it.
        inline: ["next-intl"],
      },
    },
  },
});
