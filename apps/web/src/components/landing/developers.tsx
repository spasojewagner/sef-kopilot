import { ArrowUpRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { apiUrl } from "@/lib/api";

/**
 * The same checks without the pages: a request to the HTTP API and a call of the MCP server's
 * tool, at the address of the API this build talks to.
 */
export function Developers() {
  const t = useTranslations("home.developers");
  const http = [
    `API=${apiUrl("")}`,
    `curl "$API/invoices/validate?profile=srb" \\`,
    `  -H "Authorization: Bearer $SEF_KOPILOT_KEY" \\`,
    `  -H "Content-Type: application/xml" \\`,
    `  --data-binary @${t("file")}`,
  ].join("\n");
  const mcp = [
    `POST ${apiUrl("/mcp")}`,
    "",
    `{ "jsonrpc": "2.0", "id": 1, "method": "tools/call",`,
    `  "params": {`,
    `    "name": "validate_invoice",`,
    `    "arguments": { "xml": "<Invoice …>", "profile": "srb" }`,
    `  } }`,
  ].join("\n");
  return (
    <section
      aria-labelledby="developers-title"
      className="page-width grid grid-cols-[minmax(0,1fr)] gap-10 py-20 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-16 lg:py-28"
    >
      <div>
        <h2
          id="developers-title"
          className="text-3xl leading-tight font-semibold tracking-[-0.02em] sm:text-4xl"
        >
          {t("title")}
        </h2>
        <p className="mt-5 max-w-[34rem] leading-relaxed text-muted-foreground">
          {t("text")}
        </p>
        <a
          href={apiUrl("/docs")}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-6 inline-flex items-center gap-1 rounded-sm font-medium underline decoration-brand decoration-2 underline-offset-4 outline-none hover:decoration-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50"
        >
          {t("docs")}
          <ArrowUpRight aria-hidden="true" className="size-4" />
        </a>
      </div>
      <div className="grid min-w-0 gap-5">
        {[
          ["HTTP", http],
          ["MCP", mcp],
        ].map(([name, code]) => (
          <figure key={name} className="min-w-0">
            <figcaption className="mb-2 text-sm font-medium text-muted-foreground">
              {name}
            </figcaption>
            <pre className="overflow-x-auto rounded-xl bg-background p-5 font-mono text-[0.8125rem] leading-6 surface-ink">
              <code>{code}</code>
            </pre>
          </figure>
        ))}
      </div>
    </section>
  );
}
