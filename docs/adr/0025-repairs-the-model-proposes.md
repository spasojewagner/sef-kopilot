# 25. Repairs the model proposes: the fields around the violations, checked patches, two rounds

- Status: accepted
- Date: 2026-11-06
- Deciders: Marko Spasojević
- Technical story: milestone M3, branch `feat/repair-model-loop`, the last of the three that make
  up the backlog's `feat/repair-loop-audit`; the brief's layer 3

## Context and problem statement

The patch engine applies patches and the validator judges what they leave (ADR-0023). A repair
holds them until a person decides (ADR-0024). Layer 3 still lacks its model: the brief has a
language model propose the patches, with code applying them and the validator judging the
result, the whole loop within 20 seconds. To write a patch, the model must see the invoice,
which the explainer never sends (ADR-0021). How much of the invoice does it see? How is its
answer checked before anything is applied, what does it learn from the validator, and when
does the loop stop?

## Decision drivers

- The model is never trusted (the brief). What it may not do is checked in code: by the patch
  engine, the guard and the check of values (ADR-0022), not by the prompt alone.
- The invoice goes to a third party, the provider the operator configured. The model gets what a
  patch needs, not the invoice.
- A canonical path has positions where an element has siblings of its name. A model that
  computes them gets them wrong; it should copy them.
- Only the validator's process parses an invoice the API holds (ADR-0015, ADR-0024).
- The brief's budget: the whole loop within 20 s. Groq's free tier allows 8 000 tokens a minute.
- A model's repair is a proposal like any other: the same approval, the same audit log.

## Considered options

1. **The fields around the violations, by canonical path, from the validator's process; a strict
   schema; every patch checked before it is applied; a second round told what became of each
   patch.** Chosen.
2. The whole invoice, as XML.
3. The violations alone, as the explainer sends them.
4. One round, with no word from the validator.
5. The model's patches applied as they come, and its mistakes put right in the same conversation.

## Decision outcome

**What the model is sent** (`einvoice_core.fields`, `sef_api.repairs.repairer`). It gets the first
ten fatal violations of the report, each with its rule, layer, place and message. Warnings do
not keep an invoice from being sent, and are left out. It also gets the invoice's fields around
the violations. A field is a basic component that holds text, or an attribute, given by its
canonical path with its value. The fields around a place are those of the aggregate that holds
it, or of the place itself when it is an aggregate. Around the root, they are only the root's
own fields: the number, dates, codes and currencies. There are at most sixty fields. Values are
quoted as JSON and cut at 200 characters, saying so. A field that only a person decides says
what kind it is: "a person decides: a tax identifier". Nothing in the extensions is a field. The
validator's process lists the fields in the same message that applies the patches, for the
document the patches leave. Violations and fields are data between tags, with `<` and `>`
escaped, and the prompt says that an instruction in them is never followed.

**What the model answers.** It answers one JSON schema in strict mode:
`{"patches": [{"xpath", "op", "value", "reason"}]}`, with `""` as the value of a removal, in
at most 2 048 tokens. Before anything is applied, the answer must pass four checks:

- it is that object, with at most twenty patches;
- every patch is one the core's `Patch` takes: its value fits the operation, and no character is
  one XML cannot hold;
- every path is in the grammar of canonical paths, which refuses the extensions;
- no patch names, in its value or its reason, a value the model was not sent (ADR-0022). The
  model was sent the question and the prompt. The prompt names the standards (UBL 2.1,
  EN 16931), and a reason may name them too.

Every problem of an answer goes back to the model at once, for up to three answers a round, as
the explainer does. Non-breaking hyphens and spaces become plain ones.

**Rounds.** The validator's process applies the patches kept so far and then the new ones,
always to the invoice as it is stored. A repair's patches then apply to the document they were
proposed for, which is what approval checks. A patch already kept is not applied a second time.

- A patch that failed changed nothing. It is not kept, and the document, the difference and the
  report stay what the others leave.
- A patch a person decides is kept. The person sees it as a suggestion; it changes nothing.
- A round that leaves more fatal violations than the invoice had, or than the round kept before
  it, is not kept.

While fatal violations remain, a second round asks the model again in a new conversation. It is
sent what became of each of its patches ("applied", "not applied: it touches a date…", "failed:
there is no cbc:CityName at …"), with the violations that remain and the fields around them now.
There are at most two rounds, within `SEF_REPAIR_SECONDS` (20) from the first validation to the
last. A round still running when time runs out, a round whose model fails, and one that the
validator's process cannot apply (it is busy, say) all leave what the rounds before it kept.

**The endpoint.** `POST /invoices/{id}/repairs/suggestion?language=sr|en` requires
`invoices:submit`, and works in person or with an API key. It answers 201 with the repair, which
is kept as `POST /invoices/{id}/repairs` keeps one: proposed by the caller, waiting for a person.
A new column, `repairs.model` (migration 0011), names the model that wrote the patches, and the
audit event adds `model` and `rounds`. Without a patch to keep, nothing is kept, and the status
says why:

- 409: the invoice is valid, ten of its repairs wait already, or it changed meanwhile;
- 422: the model proposed no patch that a repair keeps;
- 502: the model gave no answer, or none that could be used;
- 503: no model is configured on this server;
- 504: no round was done in time.

A suggestion counts as a validation and as a request to the language model. The limit on
explanations is now the limit on requests to the model, for explanations or a repair. Its
settings keep their names, `SEF_EXPLANATIONS_PER_MINUTE` and
`SEF_ORGANIZATION_EXPLANATIONS_PER_MINUTE`, so that no deployment's configuration changes.

### Consequences

Good:

- The model never writes a path it computed, nor an amount, date or identifier of its own, and
  no patch of its own to a field a person decides is applied. Code applies its patches, the
  validator judges them and a person approves them.
- The validator tells the model why a patch failed, in the patch engine's own words.
- A question is one to three thousand tokens: the fields of a few aggregates, not the invoice.
- A model's repair is decided, approved, superseded and audited as any other repair.

Bad / accepted:

- The provider sees parts of the invoice: the names, addresses and identifiers of the parties
  around a violation. The operator chooses the provider, or none; `SECURITY.md` says so.
- Only numbers and dates are checked. A word the model makes up, such as a city or an item's
  name, passes the check; the prompt forbids it, and the person sees it in the difference. A
  rule's message may hold an example, such as SRB-019's `(mod97) 1234567890`, and a model that
  copies it passes the check too.
- Two rounds may not be enough. The caller may ask again; that is another request, counted
  again.
- On a free tier, a second round may wait for the provider's limit. The time limit then keeps the
  first round.
- A violation in the extensions, where SEF's amounts in dinars live, cannot be repaired.
- The request holds its connection for up to 20 seconds. Running it as a job comes with the web
  interface if it is needed.

## Pros and cons of the options

### The whole invoice

- Good: the model sees everything a rule may involve.
- Bad: every invoice goes to the provider whole, attachments included. A long invoice costs more
  tokens than the free tier allows in a minute. The model would have to compute the paths.

### The violations alone

- Good: nothing of the invoice beyond what the messages quote.
- Bad: the model cannot see where an element goes, what the element next to it holds, or which
  value the invoice already has to move or rewrite.

### One round

- Good: one question, half the time and tokens.
- Bad: a patch at a place that is not there, or one that leaves a new violation, ends the repair.
  The validator's reason is exactly what the model needs to fix it.

### Patches applied as they come, mistakes put right in the same conversation

- Good: the model remembers what it tried.
- Bad: the conversation grows with every answer and every report, past the free tier's minute.
  A patch would apply to a document that is no longer the stored one, so a repair could no
  longer be applied again to the document it was proposed for.
