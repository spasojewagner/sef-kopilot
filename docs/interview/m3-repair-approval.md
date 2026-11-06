# M3 — `feat/repair-approval`

## Three questions a senior engineer would ask

**1. "Why can an API key propose a repair but not approve one?"**

Proposing changes nothing: the patches are applied to a copy, and the repair waits. An ERP that
proposes fixes for the invoices it sent is exactly what keys are for. Approving replaces an
invoice that may then be sent to the tax administration, and the brief says a person approves.
A key lives on a machine, in a configuration file or a CI secret, and can leak from there. A
decision made with a leaked key would carry the authority of the member it acts for without
that member being there. So the decision routes accept only an access token: a person who
signed in, with their role checked as for any request. With a key they answer 403, whatever the
key's permissions.

**2. "Between the proposal and the approval, the invoice could change, or your patch engine
could. How do you make sure the person approves what they saw?"**

With two digests recorded at proposal time. `based_on` is the digest of the document the
patches were applied to; `patched_sha256` is the digest of the document they left. Approval
applies the patches again in the validator's process, and goes ahead only if the invoice still
has `based_on` and the new result has `patched_sha256`. Otherwise it answers 409: propose
again. The second check matters when the server is upgraded between the two steps: a change
to the patch engine could make the same patches leave a different document. The report, which
can change with the rule sets, is taken fresh from the approval's validation.

**3. "Two people approve two different repairs of the same invoice at the same moment. What
happens, and how did you rule out a deadlock?"**

Both apply their patches, outside any transaction. Then each transaction takes the advisory
lock on the organization's stored invoices first, then the repair's row, then the invoice's row.
The first replaces the document and marks every other waiting repair of that invoice
`superseded`. The second gets the lock after the first commits, finds its repair superseded,
and answers 409. The order matters. If each approval locked its own repair before the advisory lock,
A could hold the advisory lock and wait for B's row to supersede it, while B held its row and
waited for the advisory lock: a deadlock. With the advisory lock first, approvals of one
organization take turns, and the order is the one replacing a report already uses.

## The one concept to explain unaided

**Approve what was seen, not what is there now.** A decision is bound to the digests of the
document before and after. If either has moved, the decision does not apply, and the person
looks again.

## Supporting facts worth remembering

- `POST /invoices/{id}/repairs/{repair_id}/approval` and `/rejection`; `invoices:submit` in the
  invoice's scope; in person only (403 with a key); 409 for a repair that waits for no
  decision, changes nothing, or is stale; 507 beyond the quota.
- `superseded` repairs have `decided_at` and no `decided_by`: no one decided them, an approval
  did. The approval's audit event lists them.
- Found on the way: proposing kept the repair without checking the proposer again after the
  validator's work, as storing an invoice does. A member removed meanwhile could leave a repair
  behind; fixed in the first commit.
- Twelve faults seeded in the decisions, twelve caught.
