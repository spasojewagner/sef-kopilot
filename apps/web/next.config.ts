import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

/** next-intl reads each request's language and messages from this file. */
const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

/**
 * No page is meant to be shown in another site's frame, where it could be laid under a page
 * that has the visitor press a button unawares (clickjacking): least of all the one where a
 * person lets an MCP client act for them (RFC 9700 §4.16). `frame-ancestors` tells today's
 * browsers, `X-Frame-Options` older ones.
 */
const NOT_FRAMED = [
  { key: "Content-Security-Policy", value: "frame-ancestors 'none'" },
  { key: "X-Frame-Options", value: "DENY" },
];

const nextConfig: NextConfig = {
  headers: async () => [{ source: "/:path*", headers: NOT_FRAMED }],
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
