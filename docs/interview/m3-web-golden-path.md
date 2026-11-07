# M3 — `test/web-golden-path`

## Three questions a senior engineer would ask

**1. "You have 200 component tests and 871 API tests. Why add an end-to-end test, and why only
one?"**

Because each suite tests its side against a picture of the other: the components against an
API each test scripts, the API against requests each test sends. A fault between them passes
both. The API not allowing the page's origin, the build carrying the wrong address of the API,
a session lost on reload, an upload with a content type the API refuses, a report that stays
stale after an approval on another page: seeded one at a time, each of these failed the
end-to-end test. One test, because it costs a build, two servers and a browser, and because a
second one would cover the same seams; the cases and the error paths stay in the fast suites,
where a failure points at a line.

**2. "End-to-end tests are flaky. How do you keep this one steady?"**

By removing what varies. Its own data: the API starts on a database dropped and made anew, and
the test registers an account of its own. Nothing outside: the model is a stand-in that writes
the same repair every time, so there is no key, no rate limit and no answer that changes. No
waiting by the clock: every check is a web-first assertion that retries until the page shows
it, and the servers are waited for at `/ready`, which answers 200 once the database is up and
the rule sets are compiled. Locators by role and name, as a person finds things. Ports of its
own, never a server that was already there. And no retries: a test that passes the second time
hides a race, so a failure keeps its trace and someone reads it.

**3. "Why not mock the API in the browser, or run it with the real model?"**

A mocked API tests the pages against what the test believes the API says, which is what the
component tests do already; CORS, the real answers and the real validation are the point. A
real model needs a key in CI, costs money on every pull request and answers differently from
one run to the next, so the test would fail when the model writes otherwise, which is a
question for the evaluations of M6, not for a smoke test. The stand-in lives in the launcher,
`scripts/serve_e2e_api.py`, outside the application: the API ships no test code and no setting
that would make every repair the same patch, and the repairer checks the stand-in's answers as
it checks a real model's.

## The one concept to explain unaided

**An end-to-end test is for the seams**: what can break between the pieces while every piece's
own tests pass. It walks the path a person walks, against what ships, and it stays steady only
if it owns its data, calls nothing outside and waits for what the page shows, never for a time.

## Supporting facts worth remembering

- `make e2e` or `pnpm --filter @sef-kopilot/web e2e`: Playwright builds the application with
  `NEXT_PUBLIC_API_URL=http://127.0.0.1:8100`, serves it on 3100, and starts the API on 8100 with
  `uv run python scripts/serve_e2e_api.py`. It needs `SEF_TEST_DATABASE_URL`, the rule sets and
  Chromium (`pnpm --filter @sef-kopilot/web exec playwright install chromium`).
- The scripted model answers only the repairer: for each `<violation>` with `rule: SRB-001` it
  writes 380 at the `place:` it names; 380 is in the rule's message, so the repairer does not
  take it for an invented value.
- `@playwright/test` is pinned to 1.63.0 exactly; CI installs that version's headless Chromium
  (`playwright install --with-deps --only-shell chromium`).
- `retries: 0`; `trace: "retain-on-failure"`; CI uploads `playwright-report/` and
  `test-results/` when the job fails, for 14 days.
- On Windows the servers are killed rather than stopped, which leaves `sef_e2e` behind: the next
  run drops it first.
- An approval that forgot to mark the list of invoices stale passed the test at first: the
  upload had marked the list stale, and the test had not opened it since. It now opens the list
  between the upload and the repair, and the fault fails it.
- A page that hydrates otherwise than it was built passed every step and failed only on the
  console's error (React's #418): that check is worth its line.
