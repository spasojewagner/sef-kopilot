# 26. The web application: the language in the path, shadcn/ui in the repository, the browser calling the API

- Status: accepted
- Date: 2026-11-06
- Deciders: Marko Spasojević
- Technical story: milestone M3, branch `feat/web-bootstrap`; the brief's fixed front-end stack

## Context and problem statement

The brief fixes the web stack: Next.js with the App Router, Tailwind v4, shadcn/ui, TanStack
Query, and `next-intl` with Serbian (Latin) first and English second. It leaves open how a page
knows its language, which of shadcn/ui's styles the components take and where they live, how
the pages reach the API, and how dark mode is chosen. Every page that follows (upload, report,
diff, approval) builds on the answers, so they are settled once, with the application's shell.

## Decision drivers

- Serbian (Latin) first. A shared link opens in the language it was shared in, and every page
  says its language in `lang`, for screen readers and search engines.
- Static pages wherever possible: the demo runs on free tiers, Cloudflare Pages for the web.
- The web application holds no business logic and no secret. Every `NEXT_PUBLIC_` value is
  public, because the build writes it into the code the browser loads.
- Boring, well-understood choices, and code a reviewer can trace to its upstream source.
- No call to a third party at run time: the self-hosted deployment calls only the language
  model's provider, from the API.
- Accessible components, and no flash of the wrong theme.

## Considered options

The language of a page:

1. **The first segment of every path, `/sr-Latn/…` and `/en/…`, read as the root layout's
   parameter.** Chosen.
2. A cookie or the browser's `Accept-Language`, with one address for both languages.
3. A host for each language.

The components:

1. **shadcn/ui, style `new-york` on Radix primitives, copied into the repository, with the
   `shadcn` CLI pinned as a development dependency.** Chosen.
2. shadcn/ui's newer presets on Base UI (`base-nova`, the CLI's default for a new project).
3. A component library installed as a package.

How the pages reach the API:

1. **The browser calls the API across origins, which the API allows for the configured
   origins (CORS).** Chosen.
2. Through a server of the web application that forwards each request (a back end for the
   front end).

Dark mode:

1. **The operating system's preference, in CSS alone.** Chosen.
2. A switch on the page.

## Decision outcome

**The language.** `next-intl` 4 puts the language first in every path (`localePrefix:
"always"`). The root layout is `src/app/[locale]/layout.tsx` and reads it with
`next/root-params` (Next.js 16.3 and later), so each page is rendered once per language at build
time. `src/proxy.ts` sends a path without a language to the one the browser asks for, or to
Serbian. The visitor's choice is the path and nothing else: `localeCookie: false`, so no cookie
is set. The tag is the BCP 47 `sr-Latn`, because `Intl` writes dates and months in Cyrillic
for `sr` alone. The texts are `messages/sr-Latn.json` and `messages/en.json`. The compiler
knows the Serbian keys (`AppConfig`), and a test holds the English file to the same keys and the
same arguments. A path that names no page renders the localized 404.

**The components.** They come from shadcn/ui at the version of the `shadcn` CLI that
`package.json` pins (4.23.0), with these settings, recorded in `components.json`:

- style `new-york`, which the CLI reads as `new-york-v4` for Tailwind v4, on Radix (`radix-ui`);
- base colour `neutral`, as CSS variables in `src/app/globals.css`;
- `cn` from the `cn` package, as the registry writes it, and `lucide-react` for icons.

The components are files in `src/components/ui`, with shadcn's MIT notice beside them. The CLI
could not reach the registry from the build environment, so the first two were copied from the
registry's source at the tag `shadcn@4.23.0`, as the manual installation describes.
`pnpm exec shadcn add button --diff` compares a file with the registry. The pinned package also
provides `shadcn/tailwind.css`: the variants (`data-open:` and the like) and the keyframes the
Radix components use. Text is in the system's fonts, so nothing is downloaded for them.

**Dark mode** follows `prefers-color-scheme`. The dark tokens and Tailwind's `dark:` variant
are the same media query, so no script runs before the first paint. The variant is declared
explicitly, because the CLI adds a class-based one to a stylesheet that declares none.

**The API.** The browser calls the API at `NEXT_PUBLIC_API_URL`, from `apps/web/.env.example`;
Next.js reads a web application's variables from its own directory. The API answers CORS only
for the origins in `SEF_WEB_ORIGINS`, each `https://` in production:

- no credentials: no cookie is sent or allowed;
- the methods `GET`, `POST`, `PATCH` and `DELETE`;
- the request headers `Authorization`, `Content-Type` and `Last-Event-ID`;
- `Location` and `Retry-After` readable by the page;
- a preflight kept for ten minutes.

`src/lib/api.ts` sends a request, gives up after 10 s, and turns an error into an `ApiError`
with the API's status and its `detail`. `src/lib/queries.ts` builds every question with
`queryOptions()`, so its key is defined once. TanStack Query keeps the answers: one cache per
visit in the browser, and a new one for each render on the server. An answer is fresh for a
minute. A failed request is tried once more, unless the API refused it with a 4xx. TanStack's
lint rules (`recommended-strict`) check the keys. The footer shows whether the API answers, and
which version.

**Left for the work that needs them:**

- Where a signed-in visitor's tokens are kept: in memory, in a cookie that a server of the web
  application sets, or in storage. Decided in `feat/web-upload-report`, the first page that
  signs in.
- Types generated from the API's OpenAPI document, in the same branch, which calls the first
  endpoints that need them. `GET /health` is typed by hand.
- A static export or a Node.js server for the web application: `chore/infra-deploy`. A static
  export runs no `proxy.ts`, so the redirect from `/` to a language would move to the host.
  That branch also decides how the preview deployments, each at an origin of its own, reach the
  API.

### Consequences

Good:

- Each page is static HTML in each language. A shared link keeps its language, and the
  application sets no cookie.
- The components are plain files that a reviewer can read and a test can render. Adding one is
  `pnpm exec shadcn add`, from the same registry version as the rest.
- The web application holds no secret and forwards nothing. The API, the only back end,
  enforces CORS itself, under test.
- Dark mode costs no JavaScript.

Bad / accepted:

- Every path carries the language, the home page's too: `/` is a redirect.
- The `shadcn` CLI is a development dependency of about 150 packages, kept for its stylesheet
  and for a pinned CLI. `shadcn eject` would inline the stylesheet and drop it. The CLI brings
  one low advisory, in `deepmerge`, for which no fix is published; it runs only on a
  developer's machine.
- `cn` is young (0.5, 2026). It replaces `clsx` and `tailwind-merge` with the same API, and the
  components import it by name: if it misbehaves, an alias in the bundler puts the old pair back.
- `new-york` is the line the CLI keeps for existing projects, next to the newer presets. Moving
  to one means adding the components again in its style.
- The API lists every origin of the web application, one by one.

## Pros and cons of the options

### The language in a cookie or in `Accept-Language`

- Good: shorter addresses.
- Bad: one address serves two languages. A cache or a search engine cannot tell them apart, a
  shared link opens in the recipient's language, and every page is rendered for each request.

### A host for each language

- Good: paths without a prefix.
- Bad: two hosts to deploy and certify on free tiers, and twice the origins for the API's CORS.

### The presets on Base UI

- Good: the CLI's default for a new project, on primitives that are actively developed.
- Bad: their components exist only as the registry's build, styled from a map. A copy could be
  checked only against the live registry, which the build environment cannot reach. Base UI is
  younger than Radix.

### A component library installed as a package

- Good: updates come with a version.
- Bad: its styling competes with Tailwind, and changing a component means overriding it. The
  brief names shadcn/ui.

### A server of the web application that forwards each request

- Good: one origin and no CORS; the server could keep tokens in a cookie that scripts cannot
  read.
- Bad: every request crosses two services on free tiers, with two cold starts, and the web
  application needs a server of its own. Progress streamed over SSE must pass through it. The
  question of tokens is still open, and such a server can be added for signing in alone.

### A switch on the page

- Good: a visitor can choose against the operating system.
- Bad: a script before the first paint or a flash, a stored choice, and more code, for a choice
  nobody has asked for.
