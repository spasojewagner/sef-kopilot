# 59. Credits are a ledger in the API's own database, spent one for each stored invoice, off by default

- Status: accepted
- Date: 2026-11-09
- Deciders: the team (milestone M6)
- Technical story: milestone M6, branch `feat/api-credits`; the brief's "credits per invoice",
  the stored invoices of ADR-0016, the maintainer's decision of 2026-11-09 that the project
  stays free and that Stripe, which does not take payments for businesses in Serbia, is built
  behind an interface and off in the public demo

## Context and problem statement

The brief asks for billing by credits per invoice, paid through Stripe's sandbox. The project
is free: the public demo charges nothing, and nobody on it holds a Stripe account. Yet an
operator who runs the API for others, an ERP vendor or an accounting firm, needs to meter it,
and a reader of the code should see how a metered product keeps its books. What is a credit,
what spends one, where is the balance kept, and how is it kept right when two invoices are
stored at once?

## Decision drivers

- Off by default, and off in the public demo: nothing changes for anyone who does not turn it
  on.
- The books are the API's own, in its database, whatever takes the payments later: a payment
  provider adds credits, it does not hold them.
- A balance that can be explained: every change recorded, with what caused it.
- Never below zero, under concurrency, without a lock held across a network call.

## Considered options

1. **A balance per organization and an append-only ledger beside it, in the same transaction;
   one credit spent when an invoice is stored.** Chosen.
2. A counter of stored invoices against a limit.
3. The payment provider's own metering (Stripe's usage-based billing).

## Decision outcome

**What a credit pays for.** Storing an invoice (`POST /invoices`, MCP's `store_invoice`), one
credit each. Validating without storing stays free, within its rate limits, as do the
explanations and repairs of an invoice already stored: the stored invoice is what the
organization keeps, and what it pays for. A repair approved replaces the document and costs
nothing more.

**Where it is kept.** `credit_accounts`, one row an organization with its balance, which a CHECK
keeps from going below zero; `credit_entries`, the ledger, only ever added to: the opening
credits (`SEF_STARTING_CREDITS`, 25 by default), each spend with the invoice it paid for, each
grant. A balance and its entry are written in one transaction, so the balance is always the sum
of the entries; an identity column orders the entries as they were written. The account is
opened the first time the organization spends or is given credits; until then the balance shown
is the starting credits, written nowhere.

**Never below zero.** A spend is one statement, `UPDATE … SET balance = balance - 1 WHERE
balance > 0 RETURNING balance`: of two spends of one last credit, the second waits for the
first's row lock and then finds nothing to take. It happens under the lock that storing already
takes on the organization's invoices (ADR-0016), so a refused invoice is neither stored nor
spent, and the answer is 402 with what to do.

**Who sees what.** Whoever may store invoices, a member or an API key, sees the balance
(`GET /billing`), so that an ERP can check before it sends; the owner sees the ledger
(`GET /billing/entries`). The operator gives credits with `make grant-credits`, for a
self-hosted deployment, a trial or a correction.

**Off by default.** `SEF_BILLING=off` stores without counting and `GET /billing` says so. Buying
credits is a separate decision (Stripe's sandbox behind an interface, `feat/api-stripe-checkout`);
the ledger does not depend on it.

### Consequences

Good:

- The books can be audited from the ledger alone, and they are the API's, whichever provider
  ever takes the payments.
- Correct under concurrency by a constraint and a conditional update, with no new lock.
- Nothing changes where billing is off, the public demo included.

Bad / accepted:

- One price, one credit an invoice, for every invoice: a large invoice costs what a small one
  does. Prices per size or per explanation would be a new kind of entry.
- Credits do not expire, and an organization deleted takes its ledger with it.

## Pros and cons of the options

### A counter against a limit

- Good: one number, no table.
- Bad: no history: a balance that is wrong cannot be explained, and a purchase or a grant has
  nowhere to be written.

### The payment provider's metering

- Good: invoices and usage reports come from the provider.
- Bad: the books live outside the API, every store waits on a network call, and the product
  cannot meter without an account, which this project does not have and the public demo must
  not need.
