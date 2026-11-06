# 24. Repairs of stored invoices: proposed by anyone, decided by a person, and audited

- Status: accepted
- Date: 2026-11-06
- Deciders: Marko Spasojević
- Technical story: milestone M3, branch `feat/repair-proposals`, the first of three that make
  up the backlog's `feat/repair-loop-audit`: proposals (this one), a person's decision
  (`feat/repair-approval`) and the model's proposals (`feat/repair-model-loop`)

## Context and problem statement

The patch engine (ADR-0023) applies patches to a document and validates the result, in the
core. An organization's invoices live in the API (ADR-0016), and the brief wants repairs that a
person approves, with every step in an audit log. Something must hold a repair between the
moment its patches are proposed and the moment someone decides. A human, an ERP or, soon, the
model may propose; only a person may decide. Where do patches run? What is kept of a proposal,
what may change the invoice, and what does the audit log hold?

## Decision drivers

- An invoice from the database is hostile input like one from a request. Patching it validates
  it, so it runs where validation runs (ADR-0015): the child process, within the budget and the
  time limit.
- Nothing changes an invoice without a person's decision, and nothing a machine can be given
  (an API key) can make that decision.
- A decision must apply to the document the person saw. A proposal for an invoice that has
  changed since is stale, and must not be applied.
- The audit log is a log: no invoice content in it (the brief), and it outlives what it records.
- Bounded: a proposal costs a validation, and a burst of them cannot fill the database.

## Considered options

1. **A proposal is a row: the patches applied to a copy of the invoice once, what became of
   each, the digest of the document they were applied to and of the one they left; the audit
   log is a table of events without content.** Chosen.
2. Patches kept alone and applied when someone reads the proposal.
3. The patched document kept with the proposal.
4. The audit log as structured log lines.

## Decision outcome

**Proposing** (`POST /invoices/{id}/repairs`, `invoices:submit` on an invoice the caller may
see, in person or with an API key). The body is `{"patches": [...]}`, 1 to 100 patches. The
API reads the invoice, gives its database connection back, and has the validator's child
process apply the patches and validate what they leave under the invoice's profile. The child is
sent the patches as JSON with the document, and answers with each patch's outcome, the patched
document with its report and summary, and the diff, or with a kind of failure that quotes
nothing, as for a validation. Then, in one transaction, the API locks the invoice's row and
checks that the invoice is still the document the patches were applied to (409 otherwise). It
checks that fewer than ten of its repairs wait for a decision (409 otherwise), and inserts the
repair with its audit event.

**A repair** (`repairs`) holds the outcomes (each with its patch), whether anything changed,
the verdict, the report and the diff. It keeps two digests: `based_on`, of the document the
patches were applied to, and `patched_sha256`, of the document they left. Its status is
`proposed` until a person approves or rejects it. It becomes `superseded` when the invoice
changes first. It is read through its invoice (`GET /invoices/{id}/repairs`, the latest first,
and `GET /invoices/{id}/repairs/{repair_id}`), within the same scope as the invoice, and is
deleted with it.

**Deciding** comes in the next branch, and keeps to what this one records. Only a member signed
in with an access token decides, never an API key. Approval applies the patches again to the
invoice as it is: they must be applied to the document with the digest `based_on` and leave
the one with the digest `patched_sha256`, so a decision always applies to what the person saw.
The invoice then becomes the patched document, within the storage quota.

**The audit log** (`audit_events`) is a table of events, each added in the transaction of the
change it records, so that the two are committed together. An event records the action
(`repair.proposed`, later `repair.approved` and `repair.rejected`), when, the member and the API
key, the invoice and the repair. It names them by id without a foreign key, so that it outlives
them, and goes with the organization. Its detail holds digests, the verdict and each patch's
place, operation and outcome. It never holds a value or a reason: both may quote the invoice.

**Bodies.** A list of patches is JSON that FastAPI reads whole before it validates it. Every
request body other than an invoice now passes through a middleware first. It reads the body up
to `SEF_MAX_BODY_BYTES` (1 MiB) and answers 413 beyond, whether or not the length was declared.

### Consequences

Good:

- A proposal costs one validation, on the same rate limits, and holds nothing but what it did:
  outcomes, a diff of a few lines, a report.
- A decision cannot apply to a document other than the one its proposal was shown for, and
  cannot be made with a key that leaked from an ERP.
- The audit log answers who proposed what, where in the invoice, and when, without becoming a
  second copy of the invoices; deleting an invoice does not erase the record of its repairs.
- The JSON bodies of every endpoint are bounded, the sign-in's included.

Bad / accepted:

- Approval applies the patches a second time, a second validation, rather than storing the
  patched document twice.
- Repairs are not counted against the storage quota; the limit of ten waiting per invoice and
  the rate limits bound them.
- The audit log can be read only from the database until an endpoint shows it (with the
  history of the web interface).
- A repair's reasons, written by whoever proposed it, are kept with the repair; they are
  deleted with the invoice, and never logged.

## Pros and cons of the options

### Patches kept alone, applied when read

- Good: the smallest row.
- Bad: every read costs a validation in the child process, and the outcome a person sees could
  differ from one read to the next if the rule sets change.

### The patched document kept with the proposal

- Good: approval is a copy, with no second validation.
- Bad: a second copy of every invoice for every proposal, outside the quota, or counted against
  it so that proposing fails when an organization is nearly full.

### The audit log as log lines

- Good: no table, and the log pipeline exists.
- Bad: logs are rotated and dropped, are not per organization, and cannot be committed with the
  change they record; an approval without its record, or a record without the approval, would
  be possible.
