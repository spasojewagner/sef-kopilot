# M3 — `feat/web-upload-report`

## Three questions a senior engineer would ask

**1. "Your API is Python and your front end is TypeScript. How do you keep them from drifting
apart?"**

There is one description of each answer, the API's Pydantic models, and the rest are copies a
machine makes. FastAPI writes the OpenAPI document from the models; `scripts/export_openapi.py`
keeps it in `docs/api/openapi.json`, and `openapi-typescript` turns it into
`apps/web/src/lib/api-schema.d.ts`. Both files are committed, and each has a test that generates
it again and fails when it differs: the API's suite for the document, the web suite for the
types. A change to an answer then shows in the pull request as a diff of the contract, and `tsc`
points at every page that reads the field. The export builds the API with settings of its own,
so the environment cannot change the document and make the test fail on another machine. I took
the types and not a generated client, because the client would bring its own request function
beside the one that limits the time, names the errors and refreshes the token once. The types
are a compile-time promise: nothing checks an answer in the browser, which is acceptable because
FastAPI validates each answer against its model before sending it.

**2. "The browser fetches the report anyway. Why does the report's page render on a server at
all, and what happens if you deploy it as static files?"**

Every other page is static HTML, rendered once per language at build time. This one's address
names an invoice the build never saw. With `cacheComponents`, Next.js prerenders the shell, the
header and the footer, and leaves a hole in a `<Suspense>` boundary; when the page is asked for,
a small server component awaits the id and streams one thing into the hole: the client component
that fetches the report, given the id. The server renders an id and nothing of the invoice, and
never holds the token, which stays in the browser. The cost is that the page needs Next.js at run
time. A static export cannot build a page per invoice, so if `chore/infra-deploy` goes static,
the id is read in the browser instead, from the path behind a rule of the host or from the
query. Only the page's file changes, not the address or the component (ADR-0028).

**3. "How do you show an invoice's amount in JavaScript without losing a para?"**

It never becomes a number. The API sends amounts as decimal strings, and `Intl.NumberFormat`
formats a string as an exact decimal (ECMA-402, 2023): `12345678901234567.89` keeps every digit,
where a double would make it `12345678901234568`. The decimals are set explicitly, every one the
amount has and at least two, because the browsers' data disagree: by default Node writes
`14.400,00 RSD` and Chromium `14.400 RSD`, rounding the dinar to zero decimals. A page must
never show an amount the invoice does not state. Dates are just as easy to get wrong: an issue
date is a calendar day, written in UTC so that it is the same day in every time zone, while a
moment, such as when the invoice was validated, is written in Belgrade's time. The tests write
both from Los Angeles, where midnight UTC is still the day before, because in Belgrade or in
CI's UTC a day written in the wrong zone looks right.

## The one concept to explain unaided

**One source, and copies a test checks.** The API's models are the only description of its
answers; the document and the types are generated from them and committed, and a test fails when
a copy is not its source's. The contract is then reviewed as a diff, and broken by the compiler.

## Supporting facts worth remembering

- `make openapi` runs `scripts/export_openapi.py` and then `pnpm --filter @sef-kopilot/web
  api:types` (`openapi-typescript` 7.13.0). Tests: `scripts/tests/test_export_openapi.py`,
  `apps/web/src/lib/api-schema.test.ts`. Both files are `linguist-generated`.
- The pages name answers through `Schemas` (`components["schemas"]`): `StoredInvoice`,
  `InvoicePage`, `Report`, `Violation`. A field with a default is optional in TypeScript
  (`line?: number | null`).
- The upload: `POST /invoices?profile=srb|en16931|peppol` with the XML as the body
  (`application/xml`), 60 s instead of the usual 10 s. The answer, the stored invoice with its
  report, goes into the cache under `["invoices", "one", id]` before the page moves to the
  report, and the list is asked for again.
- Errors in the visitor's language: 401, 403, 408, 413, 415, 422, 429 (the seconds from
  `Retry-After`), 503 (busy, with `Retry-After`; away, without), 507 (the quota), and an API
  that cannot be reached.
- The list: `GET /invoices?limit=20&after=…`, newest first, "Prikaži još" continues it. A
  document the parser could not read is stored too, as "Nečitljiv dokument".
- The report groups violations by rule, the fatal ones first, in the validator's order; a rule's
  message is in English as its source says it (`lang="en"`), until the explanations come.
- The report's page is `◐` in the build's table: a static shell and the id streamed into it.
  The id goes to the API encoded, as one segment of the path: `../members` stays an invoice's
  id.
- What the pages show is the uploaded document's, the rules' messages included, and it is
  rendered as text. `react/no-danger` forbids setting HTML from data, and a test renders a
  seller whose name is markup.
