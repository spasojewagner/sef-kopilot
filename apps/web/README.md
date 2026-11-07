# @sef-kopilot/web

Next.js (App Router) front end of SEF Kopilot: upload an invoice, read the validation report
and the explanations with citations, review proposed patches as a diff, approve, and follow the
send-to-SEF status. The UI is Serbian (Latin) first and English second.

## Run locally

From the repository root (Node 22 and `pnpm` via `corepack enable`):

```bash
pnpm install
pnpm --filter @sef-kopilot/web dev
```

Then open <http://localhost:3000>. The footer says whether the API answers: start it too
(`make api`), with `http://localhost:3000` among its `SEF_WEB_ORIGINS`, as in the root
`.env.example`.

## Languages

Every page is in Serbian in the Latin script and in English, with the language as the first
segment of its path: `/sr-Latn/…` and `/en/…` (`next-intl`, ADR-0026). A path without one is sent
to the language the browser asks for, or to Serbian (`src/proxy.ts`), and the language
switcher links to the same page in the other language. The locale is a BCP 47 tag because
`sr` alone means Cyrillic to the browser's date and number formats.

The texts are in `messages/sr-Latn.json` and `messages/en.json`, under the same keys; a test
fails when a key, or an argument such as `{version}`, is in one file and not the other, and the
compiler refuses a key that the Serbian file does not have. A page reads them with
`useTranslations("home")`, and a test renders it with `renderIn(locale, …)` from
`src/test/render.tsx`.

## The API

The pages call the API from the browser, at `NEXT_PUBLIC_API_URL` (see `.env.example`;
`http://127.0.0.1:8000` when it is not set), and the API allows it for the origins in its
`SEF_WEB_ORIGINS` (ADR-0026). `src/lib/api.ts` sends a request, gives up after ten seconds,
and turns an error into an `ApiError` with the API's status and reason. `src/lib/queries.ts`
holds the questions the pages ask, such as `healthQuery`, each with the key TanStack Query
keeps its answer under; `src/components/query-provider.tsx` sets how long an answer stays
fresh (a minute) and when a failed request is tried again (once, unless the API refused it).
In the tests no request leaves the machine: `vitest.setup.ts` makes each one fail as if the
API could not be reached, unless the test answers it with `vi.stubGlobal("fetch", …)`.

The answers' types come from the API's own OpenAPI document, `docs/api/openapi.json`:
`src/lib/api-schema.d.ts` is generated from it (`pnpm api:types`, or `make openapi` from the
root to write both), and a test fails when it is out of date. A type is named as the API names
the schema: `Schemas["StoredInvoiceOut"]`.

## The visitor's session

`src/lib/session.ts` keeps a signed-in visitor's session (ADR-0027). The access token stays in
the tab's memory; the refresh token and whose it is are in local storage, so that a reload or
another tab stays signed in. The tabs take turns to refresh, with the Web Locks API, because the
API spends a refresh token on use and ends a session whose spent token comes back.
`authorized()` sends a request with the access token, replaces a token the API refuses once,
and throws `SignedOutError` when no session is left. `useSession()` gives a component the
session as it changes, in this tab or in another. When a visitor signs out, or another signs
in, the visitor's cached answers are forgotten: a query key that starts with `api` holds what
the API says about itself, and every other key a visitor's data.

A visitor registers at `/sr-Latn/register`, which creates the account and its organization, or
signs in at `/sr-Latn/sign-in`; a member of several organizations chooses one there. The
header shows who is signed in, as the API confirms it, and signs out. An error is said in the
visitor's language (`authErrors` in the messages); the API's own reasons are for developers.

## Invoices

A signed-in visitor sends an invoice at `/sr-Latn/invoices`, under a profile (SEF, EN 16931 or
Peppol), and lands on its report at `/sr-Latn/invoices/{id}`; the same page lists the
organization's invoices, the newest first, with their verdicts. The report shows what the
validator read from the invoice, every rule it fails with the places it fails it, the errors
first, and what each layer of the validator found. The rules' messages are their sources'
own, in English, and are marked so. Amounts keep every decimal the invoice states. The report's
page is the same for every invoice and is built once; the id is read when the page is asked
for, and the report is fetched in the browser (ADR-0028).

What these pages show comes from an uploaded document: the parties' names, the number, and the
rules' messages, which quote the document's values. It is rendered as text, which React
escapes; the lint rule `react/no-danger` keeps anyone from setting HTML from it.

On the report, the visitor may ask for the rules to be explained, in the page's language: each
rule's card then says what the rule requires, why the invoice fails it and what to change,
with the passages of the regulations it cites, dated and linked to their sources. They come
from `POST /invoices/{id}/explanations`, which the language model answers on the API's side;
nothing is asked of it until the visitor asks, and explanations once written are kept until
the page is reloaded. A server without a language model says so.

Below the rules, the report lists the invoice's repairs, the latest first: who proposed each,
where it stands, whether the copy it leaves is valid, and what became of its patches. Each one
opens at `/sr-Latn/invoices/{id}/repairs/{repairId}`, with who decided on it, each patch and its
reason, the difference it makes to the invoice and the validator's report on the copy. The
difference is the API's, as it keeps it, and shows no line numbers: they would count the lines
of the invoice indented anew, not those of the file sent (ADR-0030).

The report of an invalid invoice offers to ask the language model for a repair. It says first
what the model is sent, asks nothing until the visitor asks, and opens the repair it writes; a
refusal says why, by the reason the API names, and offers to ask again only where that could
help (ADR-0031).

## Components and styles

The building blocks are [shadcn/ui](https://ui.shadcn.com) components in `src/components/ui`:
style `new-york` on Radix primitives (ADR-0026), copied into the repository rather than
installed as a package, so they are ours to read and change. `components.json` holds the CLI's
settings, and `pnpm exec shadcn add dialog`, run from `apps/web`, adds a component with the CLI
version that `package.json` pins. Colours, radii and dark mode are CSS variables in
`src/app/globals.css`; dark mode follows the operating system, with no switch and no script.
Class names are joined with `cn()` from `@/lib/utils`, which resolves Tailwind conflicts in
favour of the last.

## Checks

```bash
pnpm --filter @sef-kopilot/web lint        # ESLint (Next.js core-web-vitals + TypeScript rules), zero warnings
pnpm --filter @sef-kopilot/web typecheck   # next typegen + tsc --noEmit
pnpm --filter @sef-kopilot/web test        # Vitest + Testing Library (jsdom)
pnpm --filter @sef-kopilot/web build       # production build
```

Formatting is handled by Prettier from the repository root (`pnpm format`).

## Layout

```text
.env.example       the web application's settings: the API's address
components.json    shadcn/ui's settings: style, stylesheet, aliases
messages/          the interface's texts, one file per language
src/app/[locale]/  routes (App Router) under the language: the root layout, the home page,
                   `sign-in`, `register`, `invoices`, `invoices/[id]` and its
                   `repairs/[repairId]`, the 404;
                   `page.test.tsx` next to `page.tsx`
src/app/globals.css  Tailwind, shadcn/ui's theme tokens, dark mode
src/components/    components shared by the pages: the header and its account, the footer, the
                   language switcher, the API's status, the cache of the API's answers, the
                   sign-in and registration forms, the upload, the list, the report, the
                   repairs and the diff
src/components/ui/ shadcn/ui components, with their origin and license in a README
src/i18n/          the languages and the routing, the request's messages, navigation that keeps
                   the language, the messages' types
src/hooks/         hooks shared by the components: the session
src/lib/           the API client and its generated types, the session, the questions the pages
                   ask, the reader of a repair's diff; `cn()`
src/proxy.ts       sends a path without a language to the visitor's
src/test/          what the tests share: rendering in a language, with a cache of its own; an
                   API that answers as the test says; invoices and repairs to answer with
vitest.config.mts  Vitest with React plugin, jsdom and tsconfig path aliases
vitest.setup.ts    jest-dom matchers, automatic cleanup, no request to the network
```
