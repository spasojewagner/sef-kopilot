# 20. A loop around an untrusted model: copy, check, apply, tell

A language model is good at reading a violation and guessing the change that fixes it. It is
bad at what a computer does well: computing a path with positions, keeping to a value that is
exactly there, checking that a document is valid. The repair loop gives each side its part.

```text
        violations + fields (paths to copy)
   ┌──────────────────────────────────────────┐
   │                                          ▼
 validator ◄── apply ◄── check ◄── answer ◄── model
   (child)     (child)   schema,              (JSON schema,
   │                     engine,               strict mode)
   │                     values
   └── what became of each patch, what remains ──► model (a new question)
```

**Copy, don't compute.** The model is shown the invoice's fields around each violation, each by
its canonical path with positions already in it:
`/ubl:Invoice/cac:InvoiceLine[2]/cac:Item/cbc:Name = "Konsultantski sat"`. To change a field it
copies the path; to add an element it adds one step to a path it was shown. A field a person
decides is marked, so the model knows in advance that its patch will only be a suggestion.

**Check before anything happens.** An answer is data. It is parsed against the schema, every
patch against the patch engine's own model and path grammar, and every value against what the
model was sent: a date, an amount or an identifier that the question does not contain was made
up. An answer that fails goes back with what is wrong, as the explainer does. The checks are
deterministic, cheap and explainable in one sentence, so the model can act on them.

**Let the validator speak.** Code applies the patches and layer 1 validates what they leave. The
outcome of each patch ("failed: there is no cbc:CityName at …/cac:PostalAddress") is the best
feedback the model can get, because it is the system's own reason. The second round is a new,
short question: the outcomes, the violations that remain, the fields as they are now. A
conversation that grew with every answer would cost more tokens each time and drift.

**Keep the result re-appliable.** Every round applies all the patches kept so far, then the new
ones, to the invoice as it is stored. The repair can therefore be applied again to the document
it was proposed for, which is what approval does (ADR-0024). Patches that failed changed nothing
and are dropped without changing the result. A round that makes things worse is not kept.

**Bound it.** Ten violations, sixty fields, twenty patches, three answers a round, two rounds,
twenty seconds. Each limit has a reason: the provider's tokens a minute, the brief's budget, and
a person who reads the diff at the end.

The question to ask of any such loop: if the model answered with the worst thing it could, what
would reach the invoice? Here the answer is nothing a person has not approved.
