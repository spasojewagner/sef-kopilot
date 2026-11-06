# 25. A static shell with a hole: a page whose address the build cannot know

Every page of the web application is rendered when it is built, once per language (note 22).
An invoice's report cannot be: its address, `/sr-Latn/invoices/3f1e…`, names an invoice that
did not exist at build time. Next.js 16 with `cacheComponents` renders such a page in two parts
(Partial Prerendering, `◐` in the build's table):

```text
at build time, once per language        when the page is asked for
┌────────────────────────────────┐
│ header                         │
│ ┌─ <Suspense> ───────────────┐ │      ReportOf: await params → id
│ │  the fallback, until …     │◀┼───── streams <InvoiceReport id="3f1e…" />
│ └────────────────────────────┘ │      into the same response
│ footer                         │
└────────────────────────────────┘      the browser: InvoiceReport asks the API
                                         for the report, with the visitor's token
```

**The rule: what the build cannot know sits inside `<Suspense>`.** That is the id of an unknown
segment, the query, cookies and headers. The build renders everything outside the boundary, and
the boundary's fallback stands for the rest. When the page is asked for, the server sends the
shell at once and streams what is inside the boundary into the same response. Reading such data
outside a boundary stops the build with an error that names the page, instead of quietly making
the whole page dynamic, as earlier versions did.

**The hole is as small as it can be.** The page awaits its `params` in a small server component,
`ReportOf`, inside the boundary; all it renders is the client component that fetches the report,
given the id. The header's language switcher reads the current path, which is unknown too, so it
has a boundary of its own; without one, the build fails on that page.

**Why the report is fetched by the browser.** The token is in the browser (ADR-0027), and a
report belongs to the visitor's organization. The server renders an id and nothing of the
invoice, so a server of the web application never holds a token or an invoice.

**What it costs.** Static HTML is served by any host; a hole needs a server that runs Next.js
when the page is asked for. A static export cannot render it, so a static deployment would read
the id in the browser instead: from the path, with a rule of the host that serves one page for
every invoice, or from the query (ADR-0028).

The question to ask of a new page: what in it can only be known when it is asked for, and how
small can that part be?
