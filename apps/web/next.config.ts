import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

/** next-intl reads each request's language and messages from this file. */
const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const nextConfig: NextConfig = {
  // The repository keeps its own instructions for agents (AGENTS.md at its root); Next.js
  // would otherwise write one of its own into this directory on every `next dev`.
  agentRules: false,
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default withNextIntl(nextConfig);
