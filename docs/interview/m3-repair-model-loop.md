# M3 — `feat/repair-model-loop`

## Three questions a senior engineer would ask

**1. "Why not just send the model the invoice? It would see everything a rule may involve."**

For three reasons. The invoice goes to a third party, the provider the operator configured, and
a repair needs the place a rule failed, not the whole document with its attachments. A long
invoice is also more tokens than Groq's free tier allows in a minute (8 000). And a model that
reads XML has to compute the paths it patches, with positions such as `cac:InvoiceLine[2]`,
which is exactly what models get wrong. So the validator's process lists the fields around
each fatal violation: every basic component that holds text and every attribute of the
aggregate the violation is in, by canonical path and value, with the fields a person decides
marked as such. Around the root, only the invoice's own fields. At most sixty fields, values cut
at 200 characters, nothing from the extensions. The model copies a path, or adds one step to
it.

**2. "How do you stop the model from making up a value, and what still gets through?"**

Before anything is applied, every answer is checked in code, and a failure goes back to the
model with the reason, three answers a round:

- the strict JSON schema;
- the patch engine's own `Patch` model, so a value fits its operation and holds only characters
  XML allows;
- the grammar of canonical paths, which refuses the extensions;
- ADR-0022's check of values. A date, an amount, a rate or an identifier of five digits or more,
  in a patch's value or its reason, must occur in what the model was sent. Both sides are
  written one way first, so `05.10.2026.` matches `2026-10-05`.

The guard then refuses to apply any patch to an amount, VAT, an identifier or a date: it becomes
a suggestion for the person. What gets through is a word: a city or an item name the model makes
up passes the check. So does an example it copies from a rule's message, such as SRB-019's
`(mod97) 1234567890`. The prompt forbids both, and the person approves the diff, so nothing
reaches the invoice unseen.

**3. "Why two rounds, and why is the second a new conversation rather than the same one?"**

The validator knows why a patch failed ("there is no cbc:CityName at …/cac:PostalAddress"), and
that is the feedback the model needs. One round would throw that away. The second round is a new, short
question: what became of each patch, the violations that remain and the fields as they are now.
A growing conversation would cost more tokens with every answer. Each round also applies every
patch kept so far and then the new ones, always to the invoice as it is stored. So the repair is
a list of patches for the document it was proposed for, which is what approval applies again.
A patch that failed changed nothing; it is dropped, and the document, the diff and the report
stay the same. A round that leaves more fatal violations than before is not kept. Both rounds
share one deadline of 20 seconds, the validator's work included. If the second round runs out
of time, its model fails or the validator cannot apply it, the first round's repair stands.

## The one concept to explain unaided

**Give the model only what it may copy, then check that it copied it.** The fields give it the
paths, and the invoice and the messages give it the values. The checks refuse anything else
before it reaches the invoice, and the validator's own words tell it what to fix.

## Supporting facts worth remembering

- `POST /invoices/{id}/repairs/suggestion?language=sr|en`: `invoices:submit`, in person or with
  a key. It answers 201 with the repair, or with a status that says why there is none:
  - 409: the invoice is valid, ten of its repairs wait, or it changed meanwhile;
  - 422: no patch to keep;
  - 502: the model gave nothing to use;
  - 503: no model is configured;
  - 504: no round was done in time.
- The limits: ten violations, sixty fields, 200 characters a value, twenty patches an answer,
  three answers a round, two rounds, 20 s (`SEF_REPAIR_SECONDS`), 2 048 tokens an answer.
- `repairs.model` (migration 0011) names the model, and the audit event adds the model and the
  rounds. The limit on explanations now counts every request to the model.
- The validator's child process lists the fields in the same message that applies the patches.
  The API never parses an invoice itself.
