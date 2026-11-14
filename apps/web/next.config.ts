import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

import { securityHeaders } from "./src/lib/security-headers";

/** next-intl reads each request's language and messages from this file. */
const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

/** The API the pages may reach, as the build was given it; the local one otherwise. */
const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  headers: async () => [
    {
      source: "/:path*",
      headers: securityHeaders(API, process.env.NODE_ENV === "development"),
    },
  ],
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
