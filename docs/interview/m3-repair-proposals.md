# M3 — `feat/repair-proposals`

## Three questions a senior engineer would ask

**1. "The invoice is already in your database. Why apply the patches in a child process?"**

Because it is still hostile input. It was stored as it was sent, possibly malformed, deeply
nested or slow to validate, and patching ends with validating it. Validation runs in the
validator's child process for three measured reasons (ADR-0015). Saxon holds the interpreter
lock, the published rule sets cost more than linearly in the elements that fail them, and only
a process can be stopped. A patch goes the same way: the child is sent the document and the
patches as JSON, within the same budget of elements and the same time limit, and answers with
the outcomes, the patched document, its report and the diff. Every failure is a kind of answer
that quotes nothing of the document, so it can be logged.

**2. "Two requests propose a repair at the same moment, or the invoice changes while the
patches are applied. What happens?"**

The slow part, applying and validating, runs outside any transaction: the database connection
goes back to the pool first. The insert happens in a short transaction that locks the
invoice's row, then checks two things. The invoice must still have the digest of the document
the patches were applied to; otherwise the answer is 409, "propose them again". Fewer than ten
of its repairs may wait for a decision; otherwise 409 again. The lock makes the count exact
under concurrency, and the digest makes a proposal mean "these patches, on this document". The
approval in the next branch keeps to the same rule: it applies the patches only to that
document, and only if they leave the document with the digest recorded.

**3. "What is in the audit log, and why not just log a line?"**

An event per proposal: the action, when, the member, the API key if one was used, the invoice
and the repair by id. Its detail holds the digests before and after, the verdict, and each
patch's place, operation and outcome. Never a value or a reason, because both may quote the
invoice, and the brief forbids invoice content in logs. The event is added in the same
transaction as the repair, so the two are committed together or not at all, which a log line
cannot do. It names things by id without foreign keys, so that it survives the deletion of the
invoice, and it goes with the organization.

## The one concept to explain unaided

**Record a change by what identifies it, not by what it says.** Digests prove which document,
places and outcomes say what was done, and ids say who and to what. The values stay with the
invoice and leave with it, while the record of who did what stays.

## Supporting facts worth remembering

- `POST /invoices/{id}/repairs` with `{"patches": [...]}` (1 to 100), `invoices:submit`, the
  invoice's scope; counted as a validation; 201 with `Location`. Lists: latest first, 100 at
  most, without reports.
- `repairs` keeps `based_on` and `patched_sha256`. The status is `proposed`, then `approved`,
  `rejected` or `superseded`, decided in the next branch, by a person only.
- Every request body other than an invoice is read at most to `SEF_MAX_BODY_BYTES` (1 MiB)
  before FastAPI parses it, because FastAPI reads JSON whole.
- Thirteen faults seeded, thirteen caught. One was caught only after a test was added that
  proves a declared length over the limit reads none of the body.
