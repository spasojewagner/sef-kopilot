# M7 — `docs/readme-case-study`

## Three questions a senior engineer would ask

**1. "Every number in the README could be marketing. How does a reader know they are true?"**

Each one points at what produced it. The evaluation results are copied from
`evals/reports/latest.md`, which `make evals` writes and CI checks against its thresholds on
every change, so a README that disagreed with the report would be caught by reading the two side
by side. The test counts are what the suites printed on `main` when the README was written, the
performance figures are measurements kept in `docs/SESSIONS.md`, and the case study links each
claim to its decision record. Where a number cannot be shown yet, such as sending to SEF, which
no demo account backs, the README says what was tested and against what.

**2. "Why record the GIF with a scripted model? Isn't that a fake demo?"**

The GIF shows the parts that are deterministic: the validator's report, the patch engine, the
validator on the copy, the diff and the approval. Those behave the same with any model. A
scripted model makes the recording repeatable, so `make demo-gif` gives the same GIF after the
pages change, and free, so it needs no key. The page itself names the model `e2e/scripted`, and
the caption says so. What only a real model shows, an explanation with its citations, is in
the video script and in `docs/DEMO.md`, recorded from Claude and ChatGPT against the live demo.

**3. "Why frames from the DevTools protocol instead of Playwright's video?"**

Size. The repository refuses any file above 512 KB. Playwright's video is VP8, lossy: every
frame carries compression noise, so a GIF made from it changes everywhere in every frame and
came out at 2 to 5 MB. Chromium's screencast sends lossless PNG frames, and only when the page
changes, so whatever stands still is identical from frame to frame, and a GIF that stores only
what changed shrinks to under 400 KB. Less motion on the home page and jumps instead of smooth
scrolling keep it there.

## The one concept to explain unaided

**Documentation that can be checked**: every claim a reader might doubt is tied to what produced
it, a report, a test run, a decision record, or a command that makes it again, so that the
README stays true as the code changes, and a reviewer can tell when it does not.
