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

Then open <http://localhost:3000>.

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
`src/test/intl.tsx`.

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
components.json    shadcn/ui's settings: style, stylesheet, aliases
messages/          the interface's texts, one file per language
src/app/[locale]/  routes (App Router) under the language: the root layout, the pages, the 404;
                   `page.test.tsx` next to `page.tsx`
src/app/globals.css  Tailwind, shadcn/ui's theme tokens, dark mode
src/components/    components shared by the pages: the header, the footer, the language switcher
src/components/ui/ shadcn/ui components, with their origin and license in a README
src/i18n/          the languages and the routing, the request's messages, navigation that keeps
                   the language, the messages' types
src/lib/           helpers shared by the components: `cn()`
src/proxy.ts       sends a path without a language to the visitor's
src/test/          what the tests share: rendering in a language
vitest.config.mts  Vitest with React plugin, jsdom and tsconfig path aliases
vitest.setup.ts    jest-dom matchers and automatic cleanup
```
