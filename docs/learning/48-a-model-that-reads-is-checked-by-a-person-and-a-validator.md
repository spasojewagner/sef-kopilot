# A model that reads is checked by a person and a validator

A vision-language model can read a photograph of an invoice: it sees the page as a grid of
image patches, each turned into tokens, and answers in text, as it would about any picture. It
reads layouts it has never seen, in Latin or Cyrillic, crooked or in shadow. It also misreads:
an 8 for a 3, a total from the wrong row, a PIB with two digits swapped. It does so rarely, and
never says when.

So the model is given a job it can be checked on, and nothing more:

```
PDF or photo ──► pages (pictures, + text where the PDF has a text layer)
                   │
                   ▼
            reading model ──► fields: {"number": "RF-12", "issue_date": "2026-10-05",
                   │                    "totals": {"payable": "14400.00"}, ...}
                   ▼                    null where the page shows nothing
            a person: page and fields side by side, corrects, confirms
                   │
                   ▼
            code ──► UBL 2.1 (every element from a field or from SRB-CIUS, nothing computed)
                   │
                   ▼
            validator ──► XSD, Schematron, SRB-CIUS, arithmetic: valid, or why not
```

**Fields, not UBL.** The model fills in a form (structured outputs: a JSON schema the answer is
held to while it is written) with plain values: a date as `2026-10-05`, an amount as `14400.00`.
It cannot add an element, choose a namespace or invent a code the profile fixes; code does
that, the same way every time.

**Give it the text when there is text.** A PDF made by an ERP has a text layer: the characters
themselves. A model reads "14400.00" given as text more surely than drawn as pixels. So the
page is sent twice, as a picture for the layout and as text for the characters; a scan or a
photograph has only the picture.

**Write what is shown, nothing else.** A missing total is null, not computed from the lines.
Filling it in would make a wrong reading consistent, and so harder to see; left empty, the
person sees the gap and the validator names it.

**Two checks that fail differently.** The person sees the page and catches a misread name or
date; the validator's arithmetic catches lines that do not add up to the total, which a tired
person misses. Neither trusts the model, and between them a misreading has to pass both.
