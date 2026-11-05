# M2 — `chore/release-0.2.0`

## Three questions a senior engineer would ask

**1. "0.1.0 to 0.2.0: what does the minor number promise?"**

Before 1.0.0, Semantic Versioning promises nothing about compatibility: 0.2.0 says the project
grew by a milestone, and the changelog says how. What it added is the HTTP API around the core,
from accounts to explanations; what it changed is listed under Changed, such as a stored
invoice's report being its latest. Nothing holds the public API to compatibility yet; 1.0.0
(M7) will.

**2. "The changelog lists twenty-seven entries. Why write release notes as well?"**

They answer different readers. The changelog is complete, written as each pull request merged,
for whoever upgrades or reviews: Added, Changed and Fixed, line by line. The release notes are
for someone deciding whether to look at all: what the milestone does, the numbers measured, how
to try it in five commands, and what it does not do yet. Both point at the same tag, and the
notes send the rest to the changelog.

**3. "Two items of the milestone were moved, not done. Is that honest?"**

It is, if the move is recorded with its reason. Deleting finished jobs and stored invoices needs
a decision about how long accounting documents are kept, which is the maintainer's, not the
code's; it was made (30 days for jobs, a period per organization for invoices, none by default)
and the work moved to M3, beside the screens where an owner will set that period. The SEF
internal technical instruction cannot be pinned like the other sources yet, so it moved to M5,
with the SEF demo. Shipping the milestone without them is better than holding finished work
back for them.

## The one concept to explain unaided

**Keep a Changelog with SemVer.** Every pull request adds its line under Unreleased; a release
turns that section into a version heading with the date and a summary, opens a new empty
Unreleased above it, and links each version to the comparison of its tag with the one before.

## Supporting facts worth remembering

- Every package (core, API, web, workspace root) moves together, 0.1.0 to 0.2.0; `uv.lock`
  records the two Python members.
- The tag `v0.2.0` is annotated and made by the maintainer on `main`'s merge commit, after the
  merge, as `v0.1.0` was.
- 2 326 tests at the release, API coverage 100 %; the weekly check of the corpus's sources
  passed on `main` the evening before.
