# M4 — `chore/release-0.4.0`

## Three questions a senior engineer would ask

**1. "What does 0.4.0 deliver, in one breath?"**

An assistant can use SEF Kopilot the way a person does: Claude or ChatGPT connects to `/mcp`,
signs its person in through the API's own OAuth 2.1 server, with PKCE and a consent page that
says who asks, and then validates invoices, explains their errors with dated citations, reads
the rules and works on the organization's stored invoices, never beyond what the person's role
and the client's scopes allow. Around it, data has a lifetime, logs say who did what without
what anyone wrote, and errors and the model's requests are observed without the invoice.

**2. "One item of the milestone was left out. How is that honest?"**

The local embedding model was a means, not the goal: a self-hosted deployment already finds
passages by keywords, rule and business term without embeddings, and the model would add 1.5
to 2.5 GB to the image. The maintainer decided to leave it out; the backlog says so, with the
reason, and names the evaluations of M6 as what would bring it back.

**3. "How do you know the demo is real and not staged?"**

It ran against the deployed API, through each assistant's own connector and OAuth, on a
synthetic invoice in the repository; the screenshots show the tools each called, and anyone can
repeat it with the address in `docs/DEMO.md`.

## The one concept to explain unaided

**A protocol boundary is a product surface**: once a tool is exposed to an assistant, its name,
its description, its scopes and its errors are what the assistant's model reads, so they are
designed and tested like the HTTP API, and the validator stays the only judge of an invoice.

## Supporting facts worth remembering

- The demo invoice: `fixtures/invoices/synthetic/mutations/srb-009-pib-check-digit.xml`, one
  mistake, reported twice (BT-31 and BT-34).
- The tag goes on the merge commit of this pull request, whose checks passed; the release notes
  are in `.handoff/RELEASE-v0.4.0.md`.
