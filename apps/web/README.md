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
and turns an error into an `ApiError` with the API's status and reason. When the API has not
answered for ten minutes, a request first waits until it answers `/health`, for up to two
minutes, since the demo's free instance sleeps; the footer and a notice above the page say that
it is waking up (ADR-0036). `src/lib/queries.ts` holds the questions the pages ask, such as
`healthQuery`, each with the key TanStack Query keeps its answer under;
`src/components/query-provider.tsx` sets how long an answer stays fresh (a minute) and when a
failed request is tried again (once, unless the API refused it). In the tests no request leaves
the machine: `vitest.setup.ts` makes each one fail as if the API could not be reached, unless
the test answers it with `vi.stubGlobal("fetch", …)`, and has the API answer a moment before
each test, so that a request is sent at once.

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
nothing is asked of it until the visitor asks. The API keeps the explanations of a report
(ADR-0040), and the page reads those at once with `GET`, which asks the model nothing: a
report another member had explained shows its explanations without a press. A server without a
language model says so.

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

A repair that waits for a decision ends with it: an approval, which makes the invoice the copy
and supersedes the other waiting repairs, asked a second time; or a rejection, which changes
nothing. When the page cannot know whether a decision was recorded, it reads the repair again
and shows where it stands rather than sending the decision again (ADR-0032).

## The organization

`/sr-Latn/organization`, linked from the header (an icon on a phone), shows a member the
organization's name, their account and role, and how long the organization keeps its stored
invoices (ADR-0039). The role is the one the API reports now, not the one the session began
with.

The owner sets the period there, from a month to ten years, or keeps every invoice until
someone deletes it. A period that deletes invoices, where there was none or a shorter one, is
saved only after a second press that names the day up to which stored invoices go; a longer
one, or none, is saved at once. When the page cannot know whether the period was changed, it
reads it again; when the API refuses an owner who is one no longer, the page says so and shows
the role the API now reports.

## Components and styles

The building blocks are [shadcn/ui](https://ui.shadcn.com) components in `src/components/ui`:
style `new-york` on Radix primitives (ADR-0026), copied into the repository rather than
installed as a package, so they are ours to read and change. `components.json` holds the CLI's
settings, and `pnpm exec shadcn add dialog`, run from `apps/web`, adds a component with the CLI
version that `package.json` pins. Colours, radii and dark mode are CSS variables in
`src/app/globals.css`; dark mode follows the operating system, with no switch and no script.
Class names are joined with `cn()` from `@/lib/utils`, which resolves Tailwind conflicts in
favour of the last. Stylesheets are global: the Turbopack rule that runs Tailwind on every `.css`
file gives a CSS module the plain CSS type, whose class names would not be scoped, so a
component's own styles go into `globals.css` under a prefix of their own (`story-*`).

## The brand

The pages' look is a set of tokens in `src/app/globals.css` (ADR-0043), under the names the
shadcn/ui components read, so that they take it unchanged:

- **Colours**, in OKLCH: ink navy for text and the primary action, on a cool off-white with
  white cards, every grey tinted towards the navy; one accent, a teal (`brand`), which also
  marks what is valid (`success`), beside `warning` and `destructive`. Dark mode sets the same
  names, deeper. `surface-ink` is the brand's navy in both modes: it sets the tokens again for
  what it holds, so that a button inside it is light on navy with no variant of its own, and
  paints nothing itself (`bg-background` inside it is the navy).
  A state's badge is its colour's words on a tint of it (the `Badge` variants `error`,
  `warning` and `success`). `src/app/tokens.test.ts` measures every pair of tokens a page sets
  together, text at 4.5:1, the states on their tints too, and the accent and the focus ring at
  3:1, in light, in dark and on the navy; a new pairing goes into its lists.
- **Typefaces**: Onest for the text and JetBrains Mono for rule ids, paths and XML
  (`font-mono`), imported from the `@fontsource-variable` packages in the root layout and served
  with the pages. A browser loads only the ranges of characters a page has: Latin, Latin
  Extended for č, ć, đ, š and ž, Cyrillic.
- **The mark**, a compass bezel whose needle is a check: `Logo` and `LogoMark` in
  `src/components/logo.tsx`, the ring in the text's colour and the check in the accent. The
  favicon, `src/app/icon.svg`, draws the same paths in fixed colours, and a test keeps the two
  equal. `apple-icon.png` and `favicon.ico`, beside it, are rendered from it in Chromium and
  committed: after changing the mark, run `pnpm --filter @sef-kopilot/web brand:images`.
- **The header** is on the navy on every page: the logo, the sections of a member who is
  signed in, the one the page is in marked (`aria-current`), the languages and the account.
  Its first link, shown when a keyboard reaches it, leads past it to the page's content, the
  one `main` of the root layout. `page-width` is the width of the content of the header, of
  every page and of the footer, so that they line up.

## The home page

The home page is the product's page (`src/components/landing`): what it does and the way to try
it, on the brand's navy beside an example of an invoice's report; the course an invoice takes,
in four steps; the rules it is checked against; the same checks through the HTTP API and the MCP
server, at the address of the API the build talks to; and the synthetic invoices to try it on.
The example tells its story once as the page opens, with CSS alone (`story-*` in
`globals.css`): the error, the explanation, the repair and the verdict. Its end is what shows
without motion, so that a visitor who asks for less motion, or a page whose animations have not
run, shows all of it, and a screen reader reads its caption. It is drawn in the page's tokens on
the navy (`surface-page`). Behind it, `backdrop.svg` draws a chart: contour lines, the bezel of
the mark and a route that leaves it through the north-east gap.

A shared link shows `src/app/[locale]/opengraph-image.png`, which `pnpm brand:images` renders
from the mark and the backdrop. The link's image needs the site's whole address, which Vercel
gives Next.js; elsewhere the build reads it from `SITE_URL` (see `.env.example`).

## Checks

```bash
pnpm --filter @sef-kopilot/web lint        # ESLint (Next.js core-web-vitals + TypeScript rules), zero warnings
pnpm --filter @sef-kopilot/web typecheck   # next typegen + tsc --noEmit
pnpm --filter @sef-kopilot/web test        # Vitest + Testing Library (jsdom)
pnpm --filter @sef-kopilot/web build       # production build
pnpm --filter @sef-kopilot/web e2e         # the golden path in a browser (Playwright), below
```

Formatting is handled by Prettier from the repository root (`pnpm format`).

## The end-to-end test

One Playwright test walks the golden path in Chromium (`e2e/golden-path.spec.ts`, ADR-0033): a
person registers, uploads an invoice whose type code SEF does not accept, reads its report, has
the language model suggest a repair, reads its diff, approves it, and finds the invoice valid on
its report and in the list. On the way, it checks that the pages load their typeface and their
favicon, that a key leads past the header, and that the home page's example shows its end to a
visitor who asks for less motion. It runs against the application's production build and the
API as it runs, on ports of their own, 3100 and 8100, so that it runs beside `pnpm dev` and
`make api`; `playwright.config.ts` starts both and stops them afterwards. The API starts on a
database of its own, made anew each time, and a scripted model proposes the repair
(`scripts/serve_e2e_api.py`): nothing is sent to a model's provider.

It needs PostgreSQL (`make up`), named by `SEF_TEST_DATABASE_URL` as in the root `.env.example`,
the rule sets (`make rulesets`), and Chromium for Playwright, installed once:

```bash
pnpm --filter @sef-kopilot/web exec playwright install chromium
pnpm --filter @sef-kopilot/web e2e         # or `make e2e` from the root
```

A failure names its step, and keeps a screenshot and a trace of the page in `test-results/`;
`pnpm --filter @sef-kopilot/web exec playwright show-report` opens them. The build the test
makes sends the pages to its API: build again before `pnpm start`.

## Layout

```text
.env.example       the web application's settings: the API's address
components.json    shadcn/ui's settings: style, stylesheet, aliases
e2e/               the end-to-end test of the golden path (Playwright)
messages/          the interface's texts, one file per language
playwright.config.ts  the end-to-end test's browser, and the API and the build it starts
scripts/           renders the brand's raster icons from the favicon (`pnpm brand:images`)
src/app/[locale]/  routes (App Router) under the language: the root layout, the home page,
                   `sign-in`, `register`, `invoices`, `invoices/[id]` and its
                   `repairs/[repairId]`, `organization`, the 404;
                   `page.test.tsx` next to `page.tsx`
src/app/globals.css  Tailwind, the brand's tokens under shadcn/ui's names, dark mode, the
                   navy surface and the page's width; `tokens.test.ts` measures their contrast
src/app/icon.svg   the favicon, and the icons rendered from it: `apple-icon.png`, `favicon.ico`
src/components/    components shared by the pages: the logo, the header with its sections and
                   its account, the footer, the language switcher, the API's status, the cache
                   of the API's answers, the sign-in and registration forms, the upload, the
                   list, the report, the repairs and the diff, the organization's page
src/components/landing/  the home page's sections, its example of a report and its backdrop
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
