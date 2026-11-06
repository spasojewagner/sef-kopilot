# 28. The API's contract in the repository, the web application's types generated from it, and an invoice's page as a static shell

- Status: accepted
- Date: 2026-11-06
- Deciders: Marko Spasojević
- Technical story: milestone M3, branch `feat/web-upload-report`; the generated types ADR-0026
  left for the first pages that read invoices

## Context and problem statement

The pages of this branch read the API's largest answers: a stored invoice with its summary and
the validator's report (`StoredInvoiceOut`, `ValidationReport`, `Violation`, the layers), and a
page of the organization's invoices. Until now the web application described the answers it
read by hand (`/health`, the session), next to the Pydantic models from which FastAPI writes the
API's OpenAPI document. A field renamed on one side and not the other compiles, and shows
`undefined` on the page. How does the web application learn the shapes of the API's answers, so
that the two cannot drift apart unnoticed, without adding code that the browser downloads or a
running API to the build?

The report's page is also the first address with a part the build cannot know, the invoice's id,
in an application whose pages are rendered when it is built (ADR-0026). How is it rendered?

## Decision drivers

- One description of each answer: the API's models, which FastAPI already turns into OpenAPI.
- A change to the contract visible in review, in the pull request that changes the API.
- Drift caught by CI, with no API running and no network during the build.
- Nothing added to what the browser downloads. The requests stay those of ADR-0026 and ADR-0027:
  a time limit, the API's reason for an error, and the token refreshed by one tab at a time.
- A server of the web application, if it has one, never holds a token or an invoice
  (ADR-0027).
- Static pages wherever possible.

## Considered options

The contract:

1. **The OpenAPI document exported from the API's code into `docs/api/openapi.json`,
   TypeScript types generated from it with `openapi-typescript`, both kept in the repository and
   checked by tests.** Chosen.
2. Types written by hand in the web application.
3. A client generated from the document (`openapi-fetch`, Orval, Hey API).
4. The types generated during the build from a running API's `/openapi.json`.
5. The document written first, by hand, and the API tested against it (contract first).

The report's page:

1. **The address `/{locale}/invoices/{id}`, its shell rendered at build time and the id read
   when the page is asked for, streamed into the shell; the report fetched by the browser.**
   Chosen.
2. A static page that reads the id from the query: `/{locale}/invoices/report?id=…`.
3. A static page that reads the id from the path in the browser, served for every invoice's
   address by a rule of the host.

## Decision outcome

**The document.** `scripts/export_openapi.py` builds the API with settings of its own, which
read neither the environment nor a `.env` file, and writes the document as the API orders it,
indented, in UTF-8. A test of the scripts fails when the document in the repository is not the
API's, and another when the environment changes it. The document is reviewed as a diff: an
answer that loses a field shows as a removed line.

**The types.** `openapi-typescript` (7.13.0, a development dependency) writes
`apps/web/src/lib/api-schema.d.ts`: declarations only, which the compiler reads and the browser
never downloads. A Vitest test generates them again in memory and fails when the file differs,
so a document changed without its types fails the web job. `make openapi` writes the document,
then the types. The code names the answers through `Schemas` (`components["schemas"]`, in
`src/lib/api.ts`): the health check, the session's identity and tokens, and in
`src/lib/invoices.ts` the invoices' `Invoice`, `StoredInvoice`, `InvoicePage`, `Report` and
`Violation`. The paths and their query parameters are written in the function that calls each
endpoint, whose tests check them. Both generated files are marked `linguist-generated` in
`.gitattributes`, so that GitHub collapses them in a diff, and Prettier and ESLint leave them
alone.

When the API changes an answer that the pages read, `make openapi` changes the types, and `tsc`
points at every line that reads the field.

**The report's page** is `src/app/[locale]/invoices/[id]/page.tsx`. With `cacheComponents`
(Next.js 16) it is prerendered, in both languages, as a shell: the header and the footer. The
id is read from the address when the page is asked for, and streamed into the shell (Partial
Prerendering, `◐` in the build's table). All that is rendered on request is the id handed to
`InvoiceReport`, a client component that asks the API in the visitor's name, so a server of the
web application sees an invoice's id and nothing of the invoice. The id is sent encoded, as one
segment of the API's path whatever it holds, so that the page asks the API for an invoice and
nothing else: `../members` would otherwise make the browser ask for `/members`. After an upload,
the stored invoice is put in the cache under its key, so the report's page shows it without
asking again, and the list is asked for again.

What the pages show comes from an uploaded document: the parties' names, the number, and the
rules' messages, which quote the document's values. All of it is rendered as text, which React
escapes, and a lint rule forbids setting HTML from data (`react/no-danger`).

**Amounts and dates.** The API sends an amount as a decimal string. `formatAmount()` formats
the string itself, which `Intl.NumberFormat` reads as a decimal (ECMA-402, 2023), with every
decimal it has and at least two. No amount passes through a floating-point number, and no
currency's usual decimals are imposed: the browsers' data differ on the dinar's, 0 in some and
2 in others. An invoice's dates are calendar days, written in UTC so that they are the same day
everywhere; moments, such as when an invoice was validated, are written in Belgrade's time.

### Consequences

Good:

- A change to an answer of the API fails the type check of the web application that reads it,
  in the pull request that makes it, or fails a test if the generated files were not written
  again.
- The contract is reviewed as a diff, and the web application describes nothing the API
  describes.
- Nothing is added to the browser's download, and the requests are the ones they were.
- The report's page is static but for its id, and a server of the web application handles no
  invoice.
- An amount is shown with the digits the invoice states.

Bad / accepted:

- Two generated files, about 7 500 lines, in the repository, and a step (`make openapi`) after
  each change to the API; the tests say when it was forgotten.
- The types are checked when the code is compiled; nothing checks an answer in the browser.
  They say what the API's models declare, and FastAPI validates every answer against its model
  before sending it. A check at run time (zod) would describe each answer a second time.
- The types say what the document says: a field with a default is optional
  (`line?: number | null`), even where the API always sends it, so the pages check for it.
  Pydantic can mark such fields required in the schemas of answers
  (`json_schema_serialization_defaults_required`), a change to the models for when it matters.
- The report's page needs the Next.js server at run time, for its id. A static export, which
  `chore/infra-deploy` may choose (ADR-0026), cannot build a page for every invoice: that branch
  would read the id in the browser, from the path behind a rule of the host (option 3) or from
  the query (option 2). Only the page's file changes; the address and `InvoiceReport` stay.

## Pros and cons of the options

### Types written by hand

- Good: no generator, and types shaped as the pages like them.
- Bad: each answer is described twice, in two languages, and nothing tells when they differ.
  A stored invoice with its report has 38 fields in six schemas.

### A generated client

- Good: the paths and their parameters are typed too, and each request is written once.
- Bad: its own request function, beside the one that limits the time, names the errors and
  refreshes the token (ADR-0027), or a wrapper around it; and code the browser downloads.
  `openapi-fetch`, from the authors of `openapi-typescript`, is the smallest step there, if the
  endpoints the pages call grow.

### The types generated from a running API during the build

- Good: no generated file in the repository.
- Bad: the build needs a running API, its database and a network, and two builds of the same
  commit may differ. A change to the contract never shows in a diff.

### The document written first

- Good: the contract is designed before the code, and a client can be written against it at
  once.
- Bad: the API's models describe it already, so the document and the models would both be
  written by hand and tested against each other: two descriptions again. FastAPI's document says
  what the API does.

### The id in the query

- Good: a static page, which any host serves.
- Bad: an invoice's address carries its id as a parameter, unlike the API's `/invoices/{id}`
  and every other address of the application, and only the browser reads it.

### A rule of the host

- Good: the same address, and static files only.
- Bad: the rule lives in the host's configuration (`_redirects` on Cloudflare Pages), outside the
  application and its tests, and each host writes it differently. It is the way to a static
  export, if `chore/infra-deploy` chooses one.
