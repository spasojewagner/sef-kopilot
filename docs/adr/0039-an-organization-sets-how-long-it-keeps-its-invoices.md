# 39. An organization sets how long it keeps its stored invoices

- Status: accepted
- Date: 2026-11-07
- Deciders: Marko Spasojević (none by default, set by the organization, on 2026-11-06), the
  implementation by the team
- Technical story: milestone M4, branch `feat/api-invoice-retention`; stored invoices
  (ADR-0016), their repairs and the audit log (ADR-0024), the deletion of old jobs (ADR-0038),
  and `SECURITY.md` V14

## Context and problem statement

A stored invoice keeps its document, the validator's report and its repairs until a member
deletes it (ADR-0016). Data protection's storage limitation argues for a period after which it
goes, and organizations differ: an accounting office may want its clients' working copies gone
after a quarter, a company that sends from its ERP may want a year. The maintainer decided that
an invoice is kept until its organization sets a period of its own, none by default. Who sets
the period, how is it enforced, and what becomes of what refers to a deleted invoice?

The law does not ask SEF Kopilot to keep invoices. Article 15 of the Law on Electronic
Invoicing (the corpus's passage `e-invoicing-law/article-15/2026-04-01`) keeps an electronic
invoice of the private sector for ten years from the end of the year in which it was issued, in
SEF or with an information intermediary engaged to keep it, and one of the public sector
permanently in SEF. SEF Kopilot is neither: it is where an invoice is checked and repaired
before it is sent, and what it stores are working copies.

## Decision drivers

- Nothing is deleted that an owner did not choose: none by default.
- A shorter period deletes invoices for good, so who may set it, and when, must hold under
  concurrent changes of roles, and every change must be accounted for.
- The audit log outlives what it names (ADR-0024).
- No scheduler of its own: the processes that delete old jobs are there (ADR-0038).
- An API key does work on invoices, never administration (ADR-0017).

## Considered options

1. **A period on the organization, which an owner sets through `PATCH /organization`; one
   statement deletes, for every organization at once, the invoices past their period, where
   and when old jobs are deleted.** Chosen.
2. One period for the deployment, a setting like `SEF_JOB_RETENTION_DAYS`.
3. An expiry on each invoice, set when it is stored.
4. Marking invoices deleted and purging them later.

## Decision outcome

**The period is `organizations.invoice_retention_days`**, from 1 to 3 650 days, enforced by a
check constraint; empty, as migration 0012 leaves every organization, it keeps every invoice
until a member deletes it. It counts from when the invoice was stored, a time the database
records, not from the invoice's issue date, which the invoice states and a repair may change.
An approved repair replaces the document and keeps that time.

**Who may see and set it** is two permissions in the policy table (ADR-0013):

| Permission | owner | accountant | client |
| --- | :-: | :-: | :-: |
| `organization:read`: see the organization and how long it keeps its invoices | yes | yes | yes |
| `organization:manage`: set how long the organization keeps its invoices | yes | no | no |

No API key may hold either. `GET /organization` shows the name and the period;
`PATCH /organization` changes what its body names: `{"invoice_retention_days": 365}` sets a
period, `null` removes it, and a body without the field changes nothing. The change takes the
organization's lock, which changes of its members take, and checks the caller's role again
under it, so an owner demoted while the request waited changes nothing (tested at a gate).
Each change is committed with an audit event, `organization.retention_set`, whose detail is
what the period was and what it became; a request that changes nothing records nothing.

**The deletion** is one statement for every organization: it deletes the invoices whose
organization has a period and which were stored before now less that period, and returns how
many. The time of storing stands alone on one side of the comparison, so that the index of an
organization's invoices by that time (organization, time of storing, id), which the list of
invoices already has, finds the old ones without reading the others. The repairs go with their
invoice (`ON DELETE CASCADE`); the audit log names invoices by id without a foreign key, so its
events stay; the storage quota is a sum over the invoices that remain, so the room is free at
once. It runs where old jobs are deleted and when (ADR-0038), each deletion in its own
transaction, so that one that fails leaves the other done.

### Consequences

Good:

- Nothing goes that an owner did not choose, and every member can see what was chosen.
- Every change of the period says who made it, when, and from what to what.
- No scheduler, no new process: one statement in the processes that already delete old jobs.

Bad / accepted:

- The period is a minimum, not an appointment: an invoice goes at the next deletion after it
  passes it, within six hours with `SEF_JOBS=inline` and within a day with workers.
- A shorter period deletes, at that next deletion, every invoice it now leaves behind, and
  nothing brings them back. The page where an owner sets it will ask twice and say which
  invoices go; the API documents it.
- The upper bound, 3 650 days, is not the legal period, which counts from the end of the year
  of issue and can exceed it. An organization that wants its copies kept that long keeps them
  without a period.
- The deletion holds the rows it deletes until it commits. If organizations came to delete
  hundreds of thousands of invoices at once, it would go in batches.

## Pros and cons of the options

### One period for the deployment

- Good: like old jobs, one setting, no endpoint, no migration.
- Bad: one choice for every tenant, while they differ; and the maintainer decided that the
  choice is the organization's.

### An expiry on each invoice

- Good: the deletion reads one indexed column.
- Bad: a change of the period either rewrites the expiry of every stored invoice or applies only
  to new ones, which would surprise an owner who shortened it to delete old copies.

### Marking invoices deleted and purging them later

- Good: a window in which a mistaken period could be undone.
- Bad: the data stays, which is what the period is set against, and every query of invoices
  must leave out the marked ones. An owner's change is guarded instead: only owners, under the
  lock, in the audit log, and asked twice on the page.
