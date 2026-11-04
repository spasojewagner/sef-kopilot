# Hostile uploads: bytes, XML and the work they cause

An upload is hostile until proven otherwise. There are four questions, in this order: is it
too large, is it the right kind of thing, what does it do to the parser, and how much work
does it cause?

## Too large: count while reading

`Content-Length` is a claim. It may be missing (chunked transfer) or false, so checking only
the header lets a client stream gigabytes. Instead:

1. If the declared length is above the limit, answer **413** at once, without reading.
2. Otherwise read the body in chunks, add up the bytes, and stop with **413** as soon as the
   total passes the limit.
3. Give the body a deadline (**408**), so that a client sending a byte a second does not hold
   the request open.

## The wrong kind: check the media type

Anything that is not `application/xml` or `text/xml` answers **415 Unsupported Media Type**.
This guards against mistakes more than attacks; the parser decides what the bytes are.

## Hostile XML: refuse the features invoices never need

| Attack | How it works | Defence |
| --- | --- | --- |
| XXE | `<!ENTITY x SYSTEM "file:///etc/passwd">`, then `&x;` puts a server file into the document, or a URL makes the server call out (SSRF) | no entity expanded, no network access |
| Billion laughs | ten nested entities, each repeating the one before ten times: a few hundred bytes become gigabytes | no entity expanded; libxml2 also caps the amplification |
| DTD tricks | a DTD can declare entities and default attributes | no DTD loaded, and a document that declares one is refused |
| Split values | a comment inside a value, `14400<!-- -->1`, makes two text nodes; code that reads the first sees 14400 where the schema sees 144001 | comments and processing instructions dropped while parsing |

A refused document is not a server error: it is a violation in the report. The refusal of a
DOCTYPE happens after parsing, so while the parser runs, its own settings are the defence.
Tests pin them on the parser itself (`einvoice_core.xml`).

## The work: bound what one document can cost

Bytes do not measure cost. An embedded PDF is one text node, while 600 KiB of empty references
kept a validator busy for 73 s.

- **Linear code.** Find what grows faster than the input, profile a scaled-up document, and
  fix it (ADR-0014). Code that is not yours, such as published rule sets, can only be bounded.
- **A budget of elements.** Count them with a streaming parser that keeps nothing, before any
  real work.
- **A time limit you can enforce.** A thread cannot be stopped, and a C extension may hold the
  GIL (Saxon does: a 2 s transform stalled the main thread for 1.7 s). So the work runs in a
  child process, which the server kills at the limit and replaces.
- **Turns that end whole.** The server and the child exchange one message and one answer at a
  time. A turn cut short by a cancelled request would leave its answer for the next request,
  so the turn runs in a task the request awaits through a shield, and every answer names the
  message it answers.
- **Admission.** Let a few validations wait, and turn the next one away with **503** and
  `Retry-After`, instead of queueing without end.

## Payloads stay out of logs

An invoice holds tax ids, amounts and names, so no log line may contain document content. That
includes an exception's message, which can quote the input, and what native code writes to the
process's standard error, which no Python log handler sees.

So a failure logs only the type of the error, and the child process sends its streams to the
null device. A test sends a document with a unique marker through every outcome, then checks
both the log records and the file descriptors.

## In this repository

- `apps/api/src/sef_api/invoices/upload.py`: bytes, time and media type.
- `apps/api/src/sef_api/invoices/validation.py` and `validator.py`: the budget, the child
  process, the time limit and admission.
- `packages/einvoice_core/src/einvoice_core/xml.py`: the hardened parser.
- `apps/api/tests/test_invoices_validate.py`, `test_validator.py`: the attacks and the limits.

The decisions are recorded in ADR-0014 and ADR-0015.
