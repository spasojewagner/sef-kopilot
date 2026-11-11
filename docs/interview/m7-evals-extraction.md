# M7 — `feat/evals-extraction`

## Three questions a senior engineer would ask

**1. "Why three measures instead of one accuracy number?"**

Because they fail differently and call for different fixes. Accuracy per form says which
documents are hard: a PDF gives the model its text, a photograph only pixels, and one number
would let a gain on one hide a loss on the other. The invented rate is the hallucination rate:
a model that fills in a date the document does not show looks more complete and scores better
on a naive measure, so guessing is counted apart and held near zero. Validity is the user's
view: how often the review has nothing to correct. Each answers a question the others cannot.

**2. "Your documents are synthetic. Aren't the numbers flattering?"**

Yes, and the ADR says so: no stamps, creases or handwriting, one page, simulated photographs.
They are an upper bound, and that is still useful: the measure's job is to catch a regression
(a new model, a prompt change, a smaller picture) and to say which field broke, not to promise
a rate on real invoices. The brief forbids real invoices, even anonymised; synthetic ones
printed in two layouts, with scans and photographs, are the honest alternative.

**3. "The answers are replayed by a hash of the request. How does a picture recorded on Windows
replay on Linux?"**

The page is drawn by PDFium and encoded by Pillow, which may differ in their last bits between
platforms, so a hash of the picture's bytes would miss. The evaluations name each picture by
what it was drawn from: the document's SHA-256, the page, the picture's size and JPEG quality.
The same document is the same request on any machine; a changed document, size or quality is a
new one. Messages without pictures keep the key they always had, so older cassettes still hold.

## The one concept to explain unaided

**Measure a model the way it can fail**: separate how often it is wrong from how often it makes
things up, split by the kinds of input that are hard in different ways, and keep one end-to-end
number for the user's view, each failure naming the case and the field.

## Found by the recordings

**"Every amount came back null, while the names and the dates were right. Why?"**

The schema asked for every value as text, and strict structured outputs hold a model to it by
constrained decoding: at each token, only what keeps the answer valid against the schema may be
written. A value typed as text or null may begin only with a quote or with null; a model about
to write 14400.00 as a number had its likeliest token forbidden, and null was always allowed.
Asked for a JSON number, it writes the digits, which the API parses as decimals, never floats,
and keeps as text. The measure said 24 %; the recorded answers said why.
