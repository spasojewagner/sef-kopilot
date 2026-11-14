# M7 — `fix/web-reading-messages`

## Three questions a senior engineer would ask

**1. "The note on the upload page said the browser would not repeat the validator's rules.
Now it refuses to draft without a date. Isn't that the second validator?"**

No, because it checks no content. It asks for two kinds of field. One is the type, which
decides whether the draft is an invoice or a credit note, two different documents. The other
is what the UBL schema requires of a draft: without it the validator stops at the schema and
judges nothing else. That gave the report the IBM sample showed: "DocumentCurrencyCode is not
expected" where the date should have been. Whether a PIB is valid, the VAT adds up or SEF
takes the invoice is still the validator's answer. The list is narrow and has to stay true, so
a test in the API empties each field of a valid invoice in turn and pins exactly the fields
whose absence fails the schema. If the drafter changes, that test fails and points at the
web's `requiredIn`.

**2. "Why carry a reason code next to the English `problem`? Clients can read the text."**

Because a message is for a person and a code is for a program, and the two change for
different reasons. The page has to decide whether "try again" is honest. A rule that no passage
of the day's corpus concerns stays unexplained however often it is asked. That was the case for
every rule of an invoice from April 2021, older than every edition in the corpus. A model that
gave nothing usable may do better next time. Matching on English text would make every rewording
of a message a breaking change. A code (`no-passage`, `no-answer`, `late`; `none-proposed`,
`none-kept` for repairs) follows the pattern the 409s already set with `reason`, so a client
tells them apart the same way everywhere.

**3. "A busy provider now gets `Retry-After` on a 502. Why not 429 or 503?"**

Because each of those already means something else to the client. A 429 here means the caller
or their organization went over *our* limits, and the page names the reading limit. A 503 means
no model is configured, which waiting does not fix. The provider holding us to *its* limits is an
upstream failure, so it is a 502, and `Retry-After` is the honest addition. The wait is the one
the provider named, or a minute, the window free tiers count requests and tokens over. The
client still retries three times inside the request. The header covers what is left after those
retries, and only when every attempt met a busy or rate-limited provider: an unreachable one is
not called busy.

## The one concept to explain unaided

**An error is a contract with whoever reads it next.** It has to say whether acting again can
help, and it has to say it in a form the reader can act on. Give a person words about their
situation ("the values are yours to write"). Give a program a stable code. Give a retry loop a
wait. "Try again" on an error that trying again cannot fix teaches people to ignore errors.
