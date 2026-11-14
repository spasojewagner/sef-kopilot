# M7 — `chore/release-1.0`

## Three questions a senior engineer would ask

**1. "What does 1.0 promise that 0.6.0 did not?"**

That the plan of the brief is done and its edges are written down. The validator judges an
invoice against SRB-CIUS, EN 16931 and Peppol, explains each error with citations, and proposes
repairs a person approves. Since 0.6.0 it also reads PDFs and pictures into fields a person
confirms, drafted into UBL by code (beta, measured). The README tells the case study with a demo
recorded from the end-to-end test, and the security review closed the ASVS Level 1 checklist with
what it accepts written down. What 1.0 does not promise is said as plainly: it is not a certified
validator, it sends only to SEF's demo, and what needs a demo account waits.

**2. "The reading is still beta in a 1.0. Isn't that a contradiction?"**

No. A version number promises the interfaces, not that every feature is finished. The reading's
route, its MCP tools and its fields keep their shape, and the beta marks only how much to trust
what a model reads. That is why the person confirms every field, the type and what the schema
needs are asked for before anything is drafted, and the evaluation publishes its numbers per
kind of document. A beta that is measured and reviewed by a person is a stronger claim than a
feature called stable and never measured.

**3. "Why did a second agent do part of the last day's work?"**

Because some of the work needs the maintainer's machine. That means live measurements with his
model keys, a Windows recording of the demo, and clicking through the screens of a running stack.
Those were written as task files with their acceptance checks, done on branches, reported, and
reviewed commit by commit before anything was pushed, like any contributor's work. Design,
review and the decisions stayed in one place. The Groq finding came out of exactly that split:
the agent measured, and the review chose the change.

## The one concept to explain unaided

**A release is a claim with its limits attached.** The changelog's summary, the review's accepted
risks and the "not a certified validator" line are what make "1.0" mean something. Without them,
the number would promise more than the code does.
