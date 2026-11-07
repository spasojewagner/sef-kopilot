# 33. One end-to-end test of the golden path, against the API with a scripted model

- Status: accepted
- Date: 2026-11-07
- Deciders: Marko Spasojević
- Technical story: milestone M3, branch `test/web-golden-path`; the brief's "one Playwright
  smoke test for the golden path (upload → report → fix → approve)"

## Context and problem statement

The web application's 200 tests render its components in jsdom, against an API that each test
scripts. The API's tests call the application in-process, through ASGI, and give its repairer a
scripted model. Each side is tested against what it believes of the other, and nothing tested
the two together as a person meets them: a browser loading the production build, the pages
calling the API from another origin (CORS), the tokens kept in the tab and found again after a
reload, an invoice sent from a file input, the report, the diff and the verdicts as the API
writes them, and one page's cache after a write on another. Which test covers that, against
what, and how does it stay the same on every run, without a model's key?

## Decision drivers

- The golden path of the brief, upload → report → fix → approve, walked as a person walks it.
- The same result on every run, on a laptop and in CI, with no key and no cost.
- As close to what ships as it can be: the production build, and the API's own database,
  validator and repairer.
- No test code in the application, and no setting a deployment could switch on by mistake.
- One test, quick enough for every pull request, whose failure explains itself.

## Considered options

What the browser talks to:

1. **The API as it runs, with only the model replaced, by a launcher outside the application
   (`scripts/serve_e2e_api.py`).** Chosen.
2. A mock API in the browser (Playwright's routes, or Mock Service Worker).
3. The API with a scripted provider among its settings (`LLM_PROVIDER=scripted`).
4. The API with a real model.

What stands in for the model:

1. **A stand-in that answers the repairer's own question: SRB-001 repaired at the violation's
   place.** Chosen.
2. Recorded answers, replayed by request (cassettes).

What the browser loads: **the production build (`next build`, then `next start`)**, chosen, or
the development server (`next dev`).

## Decision outcome

**One test**, `apps/web/e2e/golden-path.spec.ts`, in Chromium and in Serbian. A person
registers, uploads `srb-001-invoice-type-code.xml`, whose type code 393 SEF does not accept,
reads its report (one error, SRB-001), again after a reload, finds it invalid in the list and
opens it again, asks the model for a repair, reads its diff (393 removed, 380 added), approves
it with the second press, and finds the invoice valid on its report, with the repair approved,
and in the list. No page may log an error on the way. It finds what it presses and reads as a
person does, by role, name and label, and waits for what the page shows rather than for a
time: a check or a press waits up to 15 s.

**The API** is started by the test's configuration with `scripts/serve_e2e_api.py`: the
application `make api` serves, with every route, the validator in its child process, PostgreSQL
and the jobs in its own process, and two differences. Its database, `sef_e2e` on the tests'
server (`SEF_TEST_DATABASE_URL`), is dropped, made anew and migrated at each start, so that no
run meets what one before it left. And its repairer is given `ScriptedModel`, as the API's own
tests give it a model: for a violation of SRB-001 it writes 380, a code the rule's message
names, at the violation's place, with its reason in the language asked for, and for anything
else nothing. The repairer checks its answers as it checks a real model's. The settings are the
launcher's alone, so a developer's `.env` can neither point the test at another database nor
send an invoice to a provider.

**The web application** is built for the test, with the test API's address in the code the
browser loads, and served by `next start`. The two run on ports of their own, 8100 and 3100,
beside `make api` and `pnpm dev`, and neither is ever reused: a server already there is an
error. The API is ready once `/ready` answers 200, its database up and its rule sets compiled.

**A failure** is not retried: it keeps a screenshot and a trace of the page, and CI uploads the
report for 14 days. `@playwright/test` is pinned exactly, because the browser it drives is built
for its version; CI installs that one, its headless shell and the libraries it needs.

### Consequences

Good:

- The pieces are tested together, as a person meets them. Seeded one at a time, a fault in the
  API's CORS, the build's address of the API, the session kept in the tab or its refresh, the
  upload's content type, the registration's landing page, the repair's offer and its opening,
  the diff, the decision, the report's or the list's cache after an approval, the approval's
  commit, or a page that hydrates otherwise than it was built each fails this test. The last
  fails it only by the console's error, every step passing; the list's, only because the test
  opens the list between the upload and the repair, as a person comes back to an invoice,
  where without that step the upload had left the list stale already.
- No key and no cost, and the same answer on every run.
- The application holds no test code and no setting that would answer every repair alike.

Bad / accepted:

- One more CI job, of a few minutes, with a build of the web application of its own.
- The stand-in knows one rule, and reads the repairer's question by its `rule:` and `place:`
  lines. Its own tests run it through the repairer, so a change of the question fails them,
  and not only the browser.
- One browser, one language and one screen size: Firefox, WebKit, English and phones are left
  to the component tests and to people.
- The explanations are not walked: they need the corpus loaded into the test's database, and
  they are not on the brief's path.
- The trace CI keeps holds the test's own requests: a throwaway account's tokens, for a
  database that is gone, and a synthetic invoice.

## Pros and cons of the options

### A mock API in the browser

- Good: no database and no Python; fast.
- Bad: it tests the web application against what the test believes of the API, which the
  component tests already do. CORS, the API's real answers and its validation are what this
  test is for.

### A scripted provider among the API's settings

- Good: no launcher; one setting, and the API is ready.
- Bad: test code in the application, and a setting a deployment could turn on, after which
  every repair would be the same patch.

### A real model

- Good: the whole path, the model included.
- Bad: a key in CI, a cost and a rate limit on every run, and answers that vary. A test that
  fails when the model writes otherwise tests the model, which is what M6's evaluations are for.

### Recorded answers

- Good: a real model's words, replayed.
- Bad: a recording for every request, kept in step with every change of the prompt. M6 brings
  them for the evaluations, where many answers are worth keeping; for one rule of one invoice, a
  stand-in of twenty lines says what it does.

### The development server

- Good: no build to wait for.
- Bad: not what ships. It compiles a page when it is first asked for, renders twice in strict
  mode and serves no static shell, so a fault of the build would pass.
