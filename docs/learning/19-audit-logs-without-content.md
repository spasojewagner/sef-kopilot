# Audit logs: who did what, without what it said

An audit log answers, months later, *who changed this invoice, when, through what, and what
did they change?* It is not the application's log, and the difference decides how it is built
(ADR-0024).

| | Application log | Audit log |
| --- | --- | --- |
| For | operators debugging | the organization accounting for its actions |
| Kept | days, rotated, sampled | as long as the organization exists |
| Scope | the whole server | one organization, like its data |
| Written | whenever, best effort | in the transaction of the change itself |

## In the same transaction

An event is added to the session that makes the change, and committed with it. Either both are
in the database or neither is. A log line written after the commit could be lost in a crash,
and one written before could describe a change that then failed. Neither is acceptable for "who
approved this".

## Ids, not foreign keys

An event names the member, the API key, the invoice and the repair by id, with no foreign key.
A foreign key would force a choice when the invoice is deleted: delete the event (losing the
history) or forbid the deletion (keeping data the organization wanted gone). A plain id keeps
the record and lets the data go. Only the organization is a foreign key: its events go with it.

## No content

The brief forbids invoice content in logs, and an audit log is a log. So an event holds what
identifies a change without repeating it:

- **digests** of the document before and after: they prove *which* document, without being it;
- **places and outcomes**: `/ubl:Invoice/cbc:InvoiceTypeCode`, `replace`, `applied`;
- **never a value or a reason**: "380" is the invoice's content, and a reason ("the buyer is
  Beograd d.o.o.") may quote it.

The repair itself, with its values, belongs to the invoice and is deleted with it. The event
outlives both and still says who did what, where.

## Who, exactly

The actor is the member. An API key acts for a member, so the event names both: the member and
the key. "Proposed by Ana through the ERP's key" and "proposed by Ana in person" are different
facts. Deciding is for a person only (an access token, never a key), because a key can leak
from an ERP.

## In this repository

- `sef_api.audit.record`, `models.AuditEvent`, migration 0010.
- `test_repairs.py` checks that no value or reason reaches an event.
