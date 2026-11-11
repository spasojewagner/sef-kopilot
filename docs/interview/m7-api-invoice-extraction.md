# M7 — `feat/api-invoice-extraction`

## Three questions a senior engineer would ask

**1. "A vision model can write UBL directly. Why fields, a person, and then code?"**

Because each step is checked by something that does not trust the one before. The model fills
in a form of plain values (dates, amounts, identifiers), held to a JSON schema while it writes;
it cannot add an element, choose a namespace or invent a code the profile fixes. A person
compares the fields with the page, which is easy for a form and hard for XML. Code writes the
UBL the same way every time, and the validator judges it like any invoice. A misreading has to
get past the person and the validator's arithmetic both.

**2. "The model reads a photograph. What stops a wrong total from slipping through?"**

Three things. The model is told to write only what the page shows and null otherwise, so a
missing total stays visibly missing instead of being computed into a consistent wrong answer.
A PDF's text layer is sent beside its picture, so its digits are given, not seen. And the
validator checks in Python that the lines, the VAT and the totals add up (EN 16931 `BR-CO-*`),
which catches a misread digit the person did not notice.

**3. "A PDF or an image is an attack surface. What did you do about it?"**

The type comes from the first bytes, not the header, and must agree with it. PDFium opens a PDF
without running a script or fetching anything; Pillow opens three formats only and refuses a
picture above 40 million pixels from its header, before decoding it. Sizes and pages are
limited, the work runs in a worker thread, PDFium under a lock because it is not thread-safe,
and every page is re-encoded, which also drops a photograph's GPS position. Nothing is stored
or logged, and a test pushes a marked document through success and failure to prove it.

## The one concept to explain unaided

**Put the model where a person and a program can both check it**: give it a narrow job with a
fixed output form, have a person review what it read against the source, and let deterministic
code turn the reviewed values into the artefact the rest of the system judges.
