# 37. The public demo asks for synthetic invoices, by a setting of the API

- Status: accepted
- Date: 2026-11-07
- Deciders: Marko Spasojević
- Technical story: milestone M3, branch `feat/web-demo-upload-notice`; a consequence ADR-0035
  accepted

## Context and problem statement

The public demo (ADR-0035) is open to anyone who registers. What a visitor uploads is stored in
the demo's database, and an explanation or a repair sends the invoice's violations and fields to
the language model's provider. No real invoice belongs there, and the upload must say so, with
where to find invoices that do. A self-hosted server is the opposite case: real invoices are its
purpose, and the same notice would be false there. How does the web application know that it
talks to the demo?

## Decision drivers

- The notice is shown on the demo, and only there.
- The demo's configuration is in the repository, reviewed like code (ADR-0035), not typed into a
  dashboard.
- The fact belongs to the server that stores the invoice and calls the model.
- No request more than the pages already make.

## Considered options

1. **A setting of the API, `SEF_PUBLIC_DEMO`, set in `render.yaml` and reported by
   `GET /health`.** Chosen.
2. A variable of the web application's build, `NEXT_PUBLIC_DEMO`, set on Vercel.
3. The notice on every deployment.
4. The demo told by its address in the browser.

## Decision outcome

**`SEF_PUBLIC_DEMO`**, false by default, says that a server is a public demonstration. The
Blueprint sets it to true, and Render applies it when it syncs `render.yaml` from `main`.
**`GET /health` reports it** as `public_demo`, beside the version, since it is a fact about the
process that touches no dependency. The web application already asks `/health` on every page,
for the footer.

**The upload reads that answer** and asks nothing of its own. When it says `public_demo`, a
note above the form says that what is uploaded is stored on this server, and that explanations
and repairs send the rules' messages and the invoice's fields to the language model's provider;
it asks for a synthetic invoice and links to the repository's, of made-up companies and tax
numbers. Without the answer, or on another server, the upload shows nothing more than before.

### Consequences

Good:

- One line in `render.yaml` turns the notice on; a self-hosted server never shows it.
- The API, which holds the invoice and calls the model, is the one that says where the invoice
  goes; any web application built against it says the same.
- No request more: the footer's answer is read from the cache.

Bad / accepted:

- The liveness answer carries a setting. It is static and reads no dependency, so it costs
  nothing, but `/health` says more than "up".
- The note depends on the footer's answer: a page where the health check failed shows no note.
  A visitor reaches the upload only signed in, which the API answered, so the answer is all but
  always there.

## Pros and cons of the options

### A variable of the web application's build

- Good: no change to the API.
- Bad: a setting in Vercel's dashboard, outside the repository; a build without it, pointed at
  the demo's API, would ask nothing; the fact is the API's, not the pages'.

### The notice on every deployment

- Good: nothing to set.
- Bad: false on a self-hosted server, where real invoices are the purpose; a notice that is
  always there is soon not read.

### The demo told by its address

- Good: nothing to set.
- Bad: an address in the code, which a new domain or a preview breaks.
