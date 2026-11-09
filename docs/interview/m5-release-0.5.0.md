# M5 — `chore/release-0.5.0`

## Three questions a senior engineer would ask

**1. "What does 0.5.0 deliver, in one breath?"**

A stored invoice reaches SEF's demo environment in its organization's name, and only as the
validator passed it: the owner sets the organization's key once, sealed so that no one sees it
again; an owner or an accountant sends from the report's page, an assistant once its person
grants sending, an ERP with a key that holds it; each invoice is sent once, through its request
id, and the API asks SEF where it stands until it is final.

**2. "Was any of it run against the real SEF demo?"**

Not yet, and the release says so. The client follows SEF's published OpenAPI document, and the
tests run it against a stand-in that answers as that document describes, lost answers and 429s
included. Signing in to the demo takes an eID and a company administrator's role; the maintainer
decided to release without them, and the backlog names what waits for an account: SEF's error
codes in the explanations, SEF's technical instruction in the corpus, and the points the
published documents leave open.

**3. "Why release now rather than wait for the account?"**

Because what is built is complete on its own terms and every guarantee it makes is tested:
sent once, as validated, by whom the role allows, with a scope asked for at the moment it is
used. Waiting would hold M6, the evaluations, behind an account that nothing in M6 needs; the
deferred items are recorded with their reason and taken up before 1.0.

## The one concept to explain unaided

**Idempotency through a client-chosen request id**: the submission is committed before SEF is
asked, and its id is the request id SEF deduplicates on, so a retry after a lost answer cannot
import the invoice twice, and the unknown outcome stays visible instead of being guessed.

## Supporting facts worth remembering

- Three migrations in the milestone: 0020 (the key), 0021 (submissions), 0022 (keys may send).
- The tag goes on the merge commit of this pull request, whose checks passed; the release notes
  are in `.handoff/RELEASE-v0.5.0.md`.
