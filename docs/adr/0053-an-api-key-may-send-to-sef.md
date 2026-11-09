# 53. An API key may send to SEF, for an owner or an accountant who chooses it

- Status: accepted
- Date: 2026-11-09
- Deciders: the team (milestone M5)
- Technical story: milestone M5, branch `feat/api-keys-send-to-sef`; the API keys of ADR-0017
  and the sending of ADR-0051

## Context and problem statement

An ERP validates and stores its invoices with an API key of a member (ADR-0017). Sending them to
SEF (`POST /invoices/{id}/sef`, `invoices:send`) was left to people when it arrived: a key could
hold only `invoices:validate`, `invoices:submit` and `invoices:manage`, and the table refused
any other. An ERP that issues invoices all day is the client that most needs to send them, and
it has no person at hand to press a button. A key that leaks, though, could send invoices in the
organization's name. Should a key be able to send, and on what terms?

## Decision drivers

- An ERP's work, end to end, without a person in the loop for each invoice.
- What sends in the organization's name is a member who may send, and is named afterwards.
- A key that leaks does the least harm it can, and stops as soon as its member or the owner
  acts.
- Nothing new to learn: the key's model of ADR-0017 holds.

## Considered options

1. **`invoices:send` among the permissions a key may hold, by choice, for the members whose role
   sends.** Chosen.
2. Keys never send; an ERP sends through the web application, or not at all.
3. A key of its own kind for sending, issued by owners only.

## Decision outcome

**A permission a key may hold.** `invoices:send` joins the permissions keys may hold, in the code
and in the table's check (migration 0022). As for every permission, a member gives a key only
what their role grants, so only an owner's or an accountant's key may hold it, and the page that
issues keys offers it only to them, unticked. On every request, a key allows what it holds and
what its member's role grants then: an accountant made a client stops their keys sending at
once, and a revocation stops a key at once.

**What it may send.** What the member may see: an accountant's key with `invoices:manage` sends
every invoice of the organization, without it those the key's member submitted. The route and
the MCP tool `send_to_sef_demo` do the same with it; the sending is checked again under the
invoice's lock, as for a person (ADR-0051).

**Named afterwards.** The audit log records each sending with the key it came with, besides the
member, as it does for every act of a key.

**Undoing.** Migration 0022 undone takes the permission from every key; a key that held nothing
else is revoked, holding a permission the earlier schema knows.

### Consequences

Good:

- An ERP sends what it issues, through the same route, with the same guarantees: validated
  again, sent once, watched until final.
- Whoever issued the key chose sending, and the audit log names the key behind each sending.

Bad / accepted:

- A leaked key that holds `invoices:send` can send the invoices it may see, valid ones only, to
  the SEF demo, in the organization's name, until it is revoked; keys that only validate or
  store, the default on the page, cannot.
- Rate limits count validations and requests to the model, not sendings: SEF's own limits
  answer 429, which the client tries again.

## Pros and cons of the options

### Keys never send

- Good: the smallest power for a secret that machines hold.
- Bad: the ERP, the client the API exists for, would stop at the last step of its work, or send
  with a person's session it should not hold.

### A key of its own kind for sending

- Good: a separate secret for the riskiest act.
- Bad: a second model of keys to learn and to test, for what one permission among others already
  expresses; the risk is the same secret held by the same machine.
