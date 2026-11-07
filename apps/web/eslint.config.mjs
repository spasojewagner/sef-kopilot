import { defineConfig, globalIgnores } from "eslint/config";
import pluginQuery from "@tanstack/eslint-plugin-query";
import eslintConfigPrettier from "eslint-config-prettier/flat";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // TanStack Query's rules: complete query keys, a stable client, queries built with
  // queryOptions().
  ...pluginQuery.configs["flat/recommended-strict"],
  // An invoice's values, and the rules' messages that quote them, come from an uploaded
  // document: they are rendered as text, which React escapes, and never set as HTML.
  {
    files: ["**/*.{js,jsx,mjs,ts,tsx}"],
    rules: { "react/no-danger": "error" },
  },
  // Formatting is Prettier's job: disable every stylistic rule that would fight it.
  eslintConfigPrettier,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Generated from the API's OpenAPI document (`pnpm api:types`).
    "src/lib/api-schema.d.ts",
    // What the end-to-end test leaves: its report, with the trace viewer's scripts, and traces.
    "playwright-report/**",
    "test-results/**",
  ]),
]);

export default eslintConfig;
