# 23. Patches: canonical places, the schema's order, and the fields a person decides

- Status: accepted
- Date: 2026-11-06
- Deciders: Marko Spasojević
- Technical story: milestone M3, branch `feat/repair-patch-engine`; the brief's layer 3 and its
  guardrails

## Context and problem statement

Layer 3 proposes repairs that a person approves. A model will propose them (the next branch,
`feat/repair-loop-audit`), but whoever proposes a repair, code applies it and layer 1 says
whether the result is valid. That needs four things the core does not have yet: a way to say
where a change goes, operations that cannot break the document's structure, a guard for the
fields that only a person may decide, and a view of what changed. How does a patch name its
place, where does an element it adds go, and what may no patch touch?

## Decision drivers

- The model is never trusted (ADR-0002): a patch is data, and layer 1 alone judges the result.
- The brief's guardrail, as tests: a patch that touches an amount, a VAT rate or category, a
  tax identifier (the PIB), a company identifier or a date of supply is not applied; it is shown
  as needing a person's decision.
- A patch names a place the way the validator reports one: every violation carries a canonical
  path (ADR-0008), which a model can copy.
- One patch, one change, at a bounded cost; a patch that fails changes nothing.
- The person who approves sees what changed, and nothing else.

## Considered options

1. **A patch at a canonical path, read by a grammar and walked step by step; an added element
   put where the UBL schema's sequence puts it; a guard by element name.** Chosen.
2. XPath evaluated by lxml.
3. JSON Patch (RFC 6902) on the invoice's semantic model (ADR-0003).
4. The whole corrected document from the model, judged by a diff.
5. A hand-kept table of where each element goes.

## Decision outcome

A patch is `{xpath, op, value, reason}` (`einvoice_core.patches.Patch`, strict, at most 100 at
once). `reason` is for the person who approves it.

**Places.** `xpath` is a canonical path: `/ubl:Invoice` or `/cn:CreditNote`, then `cac:` and
`cbc:` steps, each with a position where an element has siblings of its name, then `@attribute`
if the place is one (`einvoice_core.places`). It is parsed against that grammar and walked one
child at a time; nothing else of XPath is accepted (no functions, axes, wildcards or other
predicates), and the extensions (`ext:`) are not places a patch may name. A path names one place
or none, costs as many steps as it has, and a step without a position that matches several
elements is an error, not a choice.

**Operations.**

- `replace` the text of an element that holds no elements, or an attribute's value;
- `add` a basic component (`cbc:`) with its value, or an attribute: the aggregates on the way
  that are missing are added with it, and an aggregate is never added on its own;
- `remove` an element with all it holds, or an attribute; an aggregate it leaves holding
  nothing goes with it.

No patch leaves an element empty, which says nothing and which Peppol refuses
(`PEPPOL-EN16931-R008`): a value is never blank, and it holds only characters XML allows. Every
step of an `add` is checked before anything is added, so a patch that fails leaves the
document as it was.

**Where an element goes.** After the elements of its name, before the first sibling the schema
puts after it. Every UBL aggregate is an `xsd:sequence` of element references, so the order is
read once per process from the schemas the validator already fetched: the two document types
and the common aggregate components, 671 elements in 35 ms (`einvoice_core.schema_order`). An
added element is indented as its neighbours are, and its namespace is declared with its usual
prefix where the document has none for it.

**The guard** (`einvoice_core.guard`). Before a patch changes anything, what it touches is
checked: its place, every element above it, and for a removal everything the element holds. A
patch touches what a person decides if any of them is

- an amount or what one is computed from: every `*Amount` and `*Quantity`, the allowance or
  charge indicator and multiplier, every currency (`*CurrencyCode`, `currencyID`) and exchange
  rate, the totals (`cac:LegalMonetaryTotal`);
- VAT: `cac:TaxCategory`, `cac:ClassifiedTaxCategory`, the exemption reasons, `cac:TaxTotal`;
- a tax identifier: `cac:PartyTaxScheme` (the PIB) and `cbc:EndpointID` (in SEF, the PIB);
- a company identifier or account: `cac:PartyLegalEntity`, `cac:PartyIdentification`,
  `cac:PayeeFinancialAccount`;
- a date or a time: every `*Date` and `*Time`, and `cac:InvoicePeriod`, which also says when
  VAT is due;
- the document's own number (its `cbc:ID`).

UBL names a basic component by what it represents, so a suffix covers every element of its
kind. Such a patch is not applied; its outcome is `needs-decision`, naming the kind and the
element ("it touches a tax identifier (cbc:EndpointID): a person decides it").

**Outcomes and the repair.** Patches apply in order, each to the document the ones before it
left, and each ends `applied` (with the value before and after), `needs-decision` or `failed`
(with the reason). `einvoice_core.repair.repair` reads the invoice with the validator's
hardened parser, applies the patches, validates what they leave under the same profile, and
shows a unified diff of the two documents, both indented alike so that only the changes
differ, however the invoice was written. `einvoice patch INVOICE PATCHES [--output PATH]`
runs it from the command line, never over the invoice itself, and exits with 0 only when every
patch applied and the invoice is valid.

### Consequences

Good:

- The guardrail is code with tests: the fixes of the mutations that change a PIB, an electronic
  address, an amount, a unit, a date or a party identifier are refused, with nothing changed.
- A patch that undoes a mutation gives back the invoice the mutation was made from, byte for
  byte (seven of them): the invoice a person approves differs from the one sent in only where
  the patches say.
- No model and no network: a repair of a small invoice, validation included, takes 11 ms warm.
- The person who approves reads a diff of a few lines, not two documents.

Bad / accepted:

- The guard goes by names and errs towards a person: it refuses fixes a person would accept at
  once, such as a unit code `SAT` for `HUR` or the seller's VAT status. They come back as
  decisions, with the patch and its reason.
- It does not protect every field whose change matters. An applied patch may change the type
  code, a payment reference or an order reference; it still waits for a person's approval, and
  the loop will hold the values a model writes in a patch as ADR-0022 holds an explanation's.
- The extensions, where SEF's amounts in dinars live, cannot be patched at all.
- Patches are independent: a refused patch does not undo the ones before it. The person
  approves the outcome as a whole.
- The diff's line numbers count lines of the indented copies, not of the file.

## Pros and cons of the options

### XPath evaluated by lxml

- Good: nothing to parse; any path a model writes works.
- Bad: an expression may select many nodes, call functions or cost what an expression can, and
  the guard would have to understand what it selects. The validator reports canonical paths,
  which a grammar of one regular expression covers.

### JSON Patch on the semantic model

- Good: a standard, and the model of the invoice exists.
- Bad: the model is read from the document and never written back; writing UBL from it would
  rewrite the whole invoice and lose what the model does not hold, and the validator's places
  are XML paths, not JSON pointers.

### The whole corrected document from the model

- Good: one answer, any change.
- Bad: nothing can be guarded or approved change by change. A model that rewrites one amount in
  two thousand lines is caught only by comparing everything, and the answer costs as many
  tokens as the invoice.

### A hand-kept table of positions

- Good: no schema to read.
- Bad: 671 elements with children, copied from a schema the table then drifts from, when the
  validator has already fetched the schema.
