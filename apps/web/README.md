# @sef-kopilot/web

Next.js (App Router) front end of SEF Kopilot: upload an invoice, read the validation report
and the explanations with citations, review proposed patches as a diff, approve, and follow the
send-to-SEF status. The UI is Serbian (Latin) first and English second (`next-intl`, from M3).

## Run locally

From the repository root (Node 22 and `pnpm` via `corepack enable`):

```bash
pnpm install
pnpm --filter @sef-kopilot/web dev
```

Then open <http://localhost:3000>.

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
src/app/           routes (App Router); `page.test.tsx` next to `page.tsx`
vitest.config.mts  Vitest with React plugin, jsdom and tsconfig path aliases
vitest.setup.ts    jest-dom matchers and automatic cleanup
```
