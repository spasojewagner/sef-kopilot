# M3 — `feat/web-bootstrap`

## Three questions a senior engineer would ask

**1. "Why is the language in the URL? A cookie would give you shorter addresses."**

Because an address that serves two languages is two pages that no one can tell apart. A cache
or a search engine would keep one of them, a link shared by a Serbian accountant would open in
English for a colleague whose browser asks for English, and every page would have to be
rendered for each request, to read the cookie. With the language as the first segment,
`/sr-Latn/…` and `/en/…`, each page is static HTML built once per language. Next.js reads the
segment as the root layout's parameter (`next/root-params`), and `<html lang>` is always right.
Only `/` and paths without a language are redirected, by `src/proxy.ts`, to the language the
browser asks for, or to Serbian. No cookie is set at all (`localeCookie: false`). The tag is
`sr-Latn`, not `sr`, because `Intl` writes "6. новембар 2026." for `sr` and "6. novembar 2026."
for `sr-Latn`.

**2. "The browser calls the API directly. What does your CORS setting protect, and what does it
not?"**

CORS decides which pages may read the API's answers in a browser. It protects the visitor: a
page at another origin cannot read what the API tells the visitor's browser. It does not protect
the API: `curl` ignores it, and a simple request from any page still reaches the API, only its
answer is hidden. So every endpoint still requires a token or is public by name, which a test
over the routes enforces. The setting itself is a list of origins, `https://` only in production,
never `*`. It allows no credentials, so no cookie is ever sent; the token travels in
`Authorization`. A page may send that header, a JSON body and `Last-Event-ID`, and may read
`Location` and `Retry-After`. Errors carry the headers too, so a page can read why it was
refused. The alternative, a server of the web application that forwards each request, would
remove CORS but put two services with two cold starts on every request.

**3. "Why TanStack Query for one health check, and what happens when the API is down?"**

Because the health check is the first of many questions the pages will ask: the report, the
repairs, the jobs. Each is defined once with `queryOptions()`, under a key, and TanStack Query
keeps one cache of the answers for the visit, so going between pages does not ask again for a
minute. A failure is tried once more, a second later, but not when the API refused the request
with a 4xx, which would only refuse it again. Each request gives up after ten seconds. When the
API is down, the footer says "API ne odgovara" about a second after the page opens; it says
the same when CORS refuses the page's origin, because the browser reports both as a network
error. In the tests no request leaves the machine: every one fails as if the API could not be
reached, unless the test answers it.

## The one concept to explain unaided

**CORS decides which pages may read the API's answers in a browser; it is not access control.**
The API authenticates every request whatever its origin, and CORS only stops a page at an
unlisted origin from reading what the visitor's browser was told.

## Supporting facts worth remembering

- `SEF_WEB_ORIGINS`: none by default, `https://` only in production; methods `GET`, `POST`,
  `PATCH`, `DELETE`; request headers `Authorization`, `Content-Type`, `Last-Event-ID`; readable
  `Location`, `Retry-After`; a preflight kept 600 s; no credentials.
- `NEXT_PUBLIC_API_URL` is in `apps/web/.env.example`, because Next.js reads a web
  application's variables from its own directory. It is public: the build writes it into the
  code the browser loads. Without it the pages call `http://127.0.0.1:8000`.
- shadcn/ui: style `new-york` on Radix, base colour `neutral`, from the registry of `shadcn`
  4.23.0, the CLI pinned as a development dependency. Components are files in
  `src/components/ui` with shadcn's MIT notice; `pnpm exec shadcn add dialog` adds one.
- Dark mode is `prefers-color-scheme`, for the tokens and for Tailwind's `dark:` variant: no
  switch, no script, no flash.
- Left open on purpose: where tokens are kept and generated API types
  (`feat/web-upload-report`), and a static export or a server (`chore/infra-deploy`).
