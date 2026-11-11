# M7 — `feat/web-invoice-extraction`

## Three questions a senior engineer would ask

**1. "Why not let the visitor edit the drafted XML, or skip the form and draft at once?"**

Because the person is the check, and a check has to be easy to do well. A form puts each value
beside its label, in the order an invoice prints them, with the document in view; the same
values in XML are scattered among namespaces and codes a reader has to know. Drafting at once
would hand the validator an invoice no one has looked at, and it would judge only whether the
misread values add up. So the page reads, shows, waits, and only then has the API draft.

**2. "The form marks missing fields. Why not check everything the validator would, in the
browser?"**

Because there would be two validators that disagree. The page names only what SEF cannot do
without (the number, the date of issue, the currency, the parties' names and PIBs, a line, the
amount payable) and the model did not find: a cheap hint of where to look. Whether the invoice is right is the
validator's answer, given on the report it lands on, with the same rules as every upload. The
browser does not repeat them; it would drift from them.

**3. "The document is a real invoice, perhaps. Where does it go?"**

To the API once, in the request that reads it, and from there to the model's provider; the API
keeps nothing and logs nothing of it. In the page it lives at an object URL, which is given back
when the reading is discarded, replaced or left, and the picture is shown with an `<img>`
rather than `next/image`, which would send it to a server to be resized. Only the invoice made
of the reviewed fields is stored, and only when the visitor asks; the public demo says that a
document given to be read goes to the model's provider whole.

## The one concept to explain unaided

**A review screen is a control, not a convenience**: show the source beside the machine's
reading, mark what is missing, make every value editable, and commit nothing until the person
does, so the review cannot be skipped by accident.
