# 64. An assistant sends a document to be read in base64, within the limit on messages

- Status: accepted
- Date: 2026-11-11
- Deciders: the team (milestone M7)
- Technical story: milestone M7, branch `feat/mcp-extract-invoice`; the brief names the MCP tool
  `extract_from_pdf` among those of M7; ADR-0042 makes each tool do what a route does;
  ADR-0062 reads invoices from PDFs and pictures in two steps with a person between them

## Context and problem statement

`POST /invoices/extract` takes a document as the request's body, its media type in
`Content-Type`, up to `SEF_MAX_DOCUMENT_BYTES` (10 MiB). A tool of the MCP server is called with
JSON arguments in a JSON-RPC message, and every message the endpoint takes is held to
`SEF_MAX_BODY_BYTES` (1 MiB), which the endpoint buffers whole to check a call's permission
before the SDK sees it. How does an assistant hand the server a PDF or a photograph, and how
large may it be?

## Decision drivers

- A tool does what its route does, with the same checks, limits and words (ADR-0042).
- The person confirms the fields before an invoice is made of them (ADR-0062): an assistant
  must not be able to skip that step by design.
- The endpoint's limit protects every tool; raising it for one raises it for all.
- Clients differ: an agent with files can read and encode a document; a chat assistant may not
  have the bytes of an attachment at all.

## Considered options

1. **The document in base64 in a tool's argument, with its media type, within the limit on
   messages; two tools, `extract_from_pdf` and `draft_invoice`, as the two routes.** Chosen.
2. A URL the server fetches the document from.
3. A larger limit on messages for the MCP endpoint.

## Decision outcome

**Base64, two tools, the limit kept.** `extract_from_pdf` takes `document`, the bytes in base64
(the standard alphabet, checked), and `media_type`, which the document's first bytes must
match, as the route requires; it answers the route's `Extraction`. `draft_invoice` takes the
fields and answers the UBL as text, for `validate_invoice`, `explain_errors` or
`store_invoice`. The tool's description tells the assistant to show the person the fields
beside their document and have them confirm or correct each before drafting, and never to
present them as checked. A server without a reading model says so before counting, as
`explain_errors` does. With the limit on messages at 1 MiB, a document is at most about 750 KB:
a PDF a business program prints, a scan, a photograph made smaller; a larger one is read in the
web application, which takes 10 MiB.

### Consequences

Good:

- One way in for every client of the protocol, with nothing for the server to fetch.
- Every check of the route applies: the document's type from its bytes, pages, pixels, time,
  the organization's own model, the limits on requests to the model.
- The person stays between the reading and the invoice: the assistant drafts only what they
  confirmed, in a second call.

Bad / accepted:

- Base64 makes a document a third larger, and a photograph straight from a phone (2 to 4 MB)
  does not fit; the description says to make it smaller first.
- A chat assistant that cannot read an attachment's bytes cannot use the tool; an agent with
  files, or an ERP's automation, can.

## Pros and cons of the options

### A URL the server fetches

- Good: no size limit on the message; a chat assistant could pass a link.
- Bad: the server would fetch arbitrary addresses on a caller's behalf, an SSRF surface the API
  allows only for clients' metadata documents, under strict rules (ADR-0045); and a link to an
  invoice is often a signed, private URL the person did not mean to share.

### A larger limit on messages

- Good: phone photographs would fit.
- Bad: every message of every tool could then be 14 MB, buffered whole before its permission is
  known: a memory cost any caller could impose, for one tool's sake.
