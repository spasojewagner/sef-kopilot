# M3 — `chore/release-0.3.0`

## Three questions a senior engineer would ask

**1. "What does 0.3.0 deliver, in one breath?"**

An invoice that fails validation can be repaired without trusting the model: the model, a member
or an API key proposes patches, code applies them to a copy, the validator judges the result, and
only a person approves, on a diff of the invoice, with every step in an audit log. Around it, a
web application in Serbian and English for the whole path, from registration to approval, tested
end to end in a browser on every change; and a public demo on free plans that anyone can try.

**2. "Two items of the milestone moved again. How is that honest?"**

Because the move is recorded with its reason and its decider. Retention and the explanations kept
with a stored invoice's report change how long data lives and how often the model is asked; they
do not change what the milestone promised, the repair loop, the web application and the public
demo, which are done and live. The maintainer chose to release, and both are the first items of
M4, with the decisions already made about them kept.

**3. "What does the public demo cost, and what are its limits?"**

Nothing: Vercel's Hobby plan, Render's and Neon's free plans, Groq's free tier. The API sleeps
after 15 minutes without a visitor and takes about a minute to wake, which the pages say while
they wait; Render's free hours are shared with the maintainer's other services; and the demo asks
for synthetic invoices only, since what is uploaded is stored there and sent to the model's
provider when an explanation or a repair is asked for.

## The one concept to explain unaided

**A tag marks a commit, a release explains it.** The tag `v0.3.0` names the merge commit whose
checks passed; the changelog lists every change for whoever upgrades; the release notes are for
someone deciding whether to look: what it does, the numbers, how to try it, and what it does not
do yet.

## Supporting facts worth remembering

- Every package at 0.3.0: the core, the API, the web application, the workspace's root.
- ADR-0023 to ADR-0037 are this milestone's, and learning notes 18 to 34.
- The demo: <https://sef-kopilot.vercel.app>, the API at <https://sef-kopilot-api.onrender.com>.
