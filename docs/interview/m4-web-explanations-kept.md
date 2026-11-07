# M4 — `feat/web-explanations-kept`

## Three questions a senior engineer would ask

**1. "The page now sends a request as it opens. Isn't that what ADR-0029 avoided?"**

ADR-0029 avoided spending the model's requests on views nobody reads. Reading what the API
keeps is a `GET` that never asks the model and is never counted, so it costs a database read.
Asking the model still waits for the visitor's press, and only when nothing is kept.

**2. "Why one cache key for two requests?"**

Because the page asks one question: what explanations of this report, in this language, the
visit knows. The `GET` answers it with the kept set or none; asking answers it with the model's.
Under one key, everything that reads it, the report's cards and the panel, sees the latest
answer, and what changes the invoice drops both. Trying again after a failure asks again, not
reads again, since the failure was the asking's.

**3. "What if reading the kept explanations fails?"**

The page offers to ask, as if none were kept: asking reads the kept set too, so a visitor who
presses gets the kept explanations without spending anything. Only a read the page itself
cancelled, because the visitor left, is not taken for none.

## The one concept to explain unaided

**A cache key names a question, not an endpoint**: two ways of answering the same question can
share a key, as long as each answer is a whole answer to it.

## Supporting facts worth remembering

- Nothing shows while the kept set is read, so that the offer does not flash by.
- None kept is a 204, not a 404: a browser logs every 404 as an error, and a page that reads as
  it opens would log one for each report nobody has explained yet.
- The report's page asks three things as it opens: the invoice, its repairs, its explanations.
