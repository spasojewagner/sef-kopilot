# M6 — `feat/web-organization-model-key`

## Three questions a senior engineer would ask

**1. "The form checks the key and the model name. Doesn't the API check them anyway?"**

It does, and the API is what decides. The page repeats the same two rules (8 to 300 visible
characters without spaces; a model's name of letters, digits and `. _ : / -`, starting with a
letter or a digit) so that an owner sees what is wrong while typing, and so that a key that
cannot be one never leaves the browser. The rules are kept beside the API's in
`lib/organization.ts` and tested with the same boundaries; a 422 still has its own message in
case they ever drift.

**2. "Why does the page not show the key, even partly, after it is saved?"**

Because the API never returns it: the token is sealed and only the server's secret opens it.
The page can say which provider and model write and since when, which is what a member needs to
know where their invoices go. Showing the last characters would mean the API keeping them in the
clear beside the token, for little gain.

**3. "What happens to the cache when the owner saves?"**

The answer of `PUT /organization/model-key` is exactly the organization's `model_key`, so the
page writes it into the organization's query instead of reading the organization again; a
removal writes null. When the outcome is uncertain (no answer, a 5xx) the organization is read
again; a 403 means the visitor is no longer the owner, so their role is read again.

## The one concept to explain unaided

**Optimistic knowledge versus certain knowledge in a cache**: a mutation's own answer is
certain and can be written into the query cache directly; a failure whose outcome the page
cannot know must not be guessed at, and the only honest move is to read the server again.

## Supporting facts worth remembering

- The card sits between the key to SEF and the API keys; only an owner sees the form.
- The model field shows the provider's default model as its placeholder; left empty, null is
  sent and the provider's default writes.
- Buttons name the model key ("Save the model key") so that they never clash with the SEF key's
  on the same page.
