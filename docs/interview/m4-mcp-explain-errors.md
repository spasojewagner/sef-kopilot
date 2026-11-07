# M4 — `feat/mcp-explain-errors`

## Three questions a senior engineer would ask

**1. "Why does `explain_errors` take the invoice's XML again, rather than the id of a stored
invoice?"**

It stands for `POST /invoices/explain`, which stores nothing: an assistant already holds the
document, and storing it is a choice with consequences of its own, such as the organization's
retention period (ADR-0039). The tools on stored invoices come next; there, the explanations
kept with a report (ADR-0040) make a second request free.

**2. "The client has a language model of its own. Why should the server's model explain?"**

Because the server's model is fenced in: it is given the passages retrieval found for the
rule, dated by the invoice's issue date, and an answer that cites anything else fails
(ADR-0021). The client's model has no corpus and no such check; asked to explain SRB-009 by
itself, it could cite a law that does not say so. The server answers what it checked, and the
client's model relays it.

**3. "Can the client's model still misquote the citations?"**

It can paraphrase, since its prose is its own. The tool's description tells it to quote the
citations rather than add law of its own, and every citation carries its document, its
version, the dates it is in force and its source's address, so that a person can check it.

## The one concept to explain unaided

**Check where you can, relay where you cannot**: the answer worth trusting is made where it can
be checked, on the server, and an untrusted layer downstream is asked to pass it on, not to
make another.

## Supporting facts worth remembering

- The model of the server is asked once a rule, at most `SEF_MAX_EXPLANATIONS` rules a call; a
  call counts as a validation and as a request to the model.
- A server without a model refuses before counting anything, as the route does.
