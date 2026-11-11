# M7 — `feat/mcp-extract-invoice`

## Three questions a senior engineer would ask

**1. "Why two tools? One tool could read the document and return the UBL."**

Because the person has to be between them. ADR-0062's guarantee is that no invoice is made of
fields nobody checked; one tool would hand the assistant a finished UBL and make the review
optional. With two, the assistant reads, shows the person the fields, and drafts only what they
confirmed, in a second call; the description of the first tool says so in the words the
assistant reads. The routes are split the same way, and each tool does what its route does.

**2. "Why base64 in a JSON argument, and not a URL the server downloads?"**

A URL makes the server fetch arbitrary addresses on a caller's behalf: an SSRF surface the API
allows only for OAuth clients' metadata documents, behind strict rules. And a link to an invoice
is often a signed private URL. Base64 keeps every byte under the caller's control and every
check of the route in place: the type from the first bytes, pages, pixels, time, limits.

**3. "1 MiB per message is small for a phone photo. Why not raise it?"**

The endpoint buffers each message whole to check the call's permission before the SDK parses
it; a 14 MB limit would let any caller make the server hold 14 MB per request, for every tool,
for one tool's sake. A PDF from a business program or a scan fits in 750 KB; a photograph is
made smaller first, as the description says, or read in the web application, which takes 10 MiB.

## The one concept to explain unaided

**An agent's tools encode the workflow's controls**: split a tool where a human decision must
happen, say in the tool's description what the agent must do with its answer, and keep each
tool's limits and checks those of the route it stands for.
