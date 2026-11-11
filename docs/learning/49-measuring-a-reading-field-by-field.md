# Measuring a reading field by field

A model that reads invoices is right or wrong one field at a time. "It read 27 of 30 documents
correctly" hides what matters: which fields it gets wrong, on which kind of document, and
whether it made anything up. So the reading is measured three ways at once.

```
golden invoice (fields)  ──print──►  PDF with text │ scan │ photograph
        │                                   │
        │                              reading model
        │                                   ▼
        └──────────── compare ◄──── fields read
                         │
     ┌───────────────────┼──────────────────────────┐
     ▼                   ▼                          ▼
 fields it has,      fields it leaves empty,    the fields read, drafted
 read as it has      filled in all the same     and validated: accepted
 them (per form)     (invented)                 as read? (valid)
```

**Accuracy, per form.** Of the fields an invoice has, the share read as it has them. A PDF gives
the model its text, a scan and a photograph only pixels; one number for all three would let a
change that helps PDFs hide one that hurts photographs. Amounts are compared as numbers (8 and
8.00 are the same quantity), text with its spaces collapsed, and a missed line counts each of
its fields: the person has to type them all.

**Invention, apart.** Of the fields an invoice leaves empty, the share the model filled in: a
date of supply copied from the date of issue, an email made up for the buyer, a line that is
not there. This is the hallucination rate, and it is kept apart from accuracy because the two
fail differently: a misread field looks wrong beside the document, an invented one looks
complete. A model can raise its accuracy by guessing; this measure is what catches it.

**Validity, end to end.** The share of documents whose fields, as read, make an invoice the
validator accepts. It answers the user's question, "will I have to correct anything?", but not
the engineer's: it does not say which field, and a wrong value the validator cannot check (a
company number has no check digit) passes it. Hence the field measures beside it.

**Golden data that cannot lie.** The reference is the fields, written first; the documents are
printed from them. Each golden invoice's fields are first drafted and validated, so a reading
that does not validate is the reading's fault, never the golden set's.

**Replaying pictures across machines.** The answers are recorded once and replayed offline
(learning note 45), keyed by what was sent. A page drawn from a PDF on Windows and on Linux can
differ in its last bits, so a picture is keyed by the document it was drawn from (its SHA-256,
the page, the picture's size), not by its bytes: same document, same request, on any machine.
