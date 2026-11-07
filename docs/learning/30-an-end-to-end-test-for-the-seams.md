# 30. An end-to-end test for the seams: what only it can catch, and how it stays steady

Each layer of the project is tested on its own, against a picture of its neighbours:

```text
  1 test        end to end   a browser, the production build, the API, PostgreSQL, the
                             validator and the repairer, with a scripted model
  200 tests     the pages    components in jsdom, against an API each test scripts
  871 tests     the API      its routes in-process (ASGI), a real database, a scripted model
  1 750 tests   the core     the validator and the patch engine, on documents
```

The component tests know what the API answers because each test says so; the API's tests know
what a page sends because each test sends it. A fault between them passes both. These are
**seams**, and the project has more than it looks:

- the API allows the page's origin and the headers it sends (CORS), or the browser refuses;
- the build wrote the right address of the API into the code (`NEXT_PUBLIC_API_URL` is fixed
  when the application is built, not when it runs);
- the session survives a reload: the refresh token in local storage, a refresh, the report's
  page reading its id from the address;
- the upload's content type is one the API takes; the report, the diff and the verdicts are
  what the API writes, not what a test wrote for it;
- after an approval on one page, the report and the list on others show the new invoice.

One end-to-end test walks the path a person walks and crosses every one of them. It costs more
than a unit test: a build, two servers, a browser, seconds instead of milliseconds, so there is
one, for the path that must never break, and the details stay in the fast tests below it.

**Steady, or worthless.** An end-to-end test that fails one run in twenty teaches everyone to
press "re-run". What makes this one give the same answer every time:

- **Its own data.** The API starts on a database made anew, and the test registers an account
  of its own: no run depends on what another left.
- **Nothing outside.** The language model is a stand-in that answers the same way every time;
  no key, no network, no cost. The model's quality is measured elsewhere (M6's evaluations).
- **Waiting for what the page shows, never for a time.** `await expect(locator).toBeVisible()`
  retries until it holds or the time runs out; a `sleep(2000)` is too long on a laptop and too
  short on a busy runner.
- **Finding things as a person does**: by role, name and label (`getByRole("button", { name:
  "Odobri", exact: true })`), so a change of a class or of the markup's nesting does not break
  it, and a page whose button has no name does.
- **Ready means ready.** The servers are waited for at `/ready`, which answers 200 only once
  the database is up and the rule sets are compiled; ports of their own, never a server that
  was already running.
- **No retries.** A test that passes the second time hides a race. When it fails, its trace
  (each step, the page's DOM, its network) says where.

**Know why it passes.** Seed a fault and watch the test fail. Here, an approval that forgot to
mark the list of invoices stale passed at first: the list was stale already, since the upload
marks it so and the test had not looked at it since. A step that opens the list between the
upload and the repair made the check mean what it says.

The question to ask of any system with parts tested apart: what could break between the parts,
while each part's own tests still pass, and which test would notice?
