# M3 — `feat/repair-patch-engine`

## Three questions a senior engineer would ask

**1. "The model will write the path. Why not evaluate it as XPath, which lxml does for free?"**

Because an XPath expression is a program. `//cbc:Note` selects every note, `cbc:ID[last()]`
picks one by a rule, `//*[contains(., 'RS')]` searches the whole document, and an expression
can cost as much as its author likes. The guard would then have to work out what an expression
selects before deciding whether it may change it. The validator already reports every place as
a canonical path: child steps, with a position only among siblings of the same name. So a patch
must use that form, and the engine reads it with one regular expression and walks it one child
at a time. A path names one place or none, costs as many steps as it has, and a step without a
position that matches two elements is an error rather than a guess.

**2. "How does the engine know where an added element goes? And why not keep a table?"**

Every UBL aggregate is an `xsd:sequence`: its children must come in the schema's order, or XSD
validation fails. The engine reads that order from the UBL 2.1 schemas the validator has
already fetched: each declared element's type is a sequence of element references, 671 elements
in 35 ms, once per process. An added element goes after the elements of its name and before
the first sibling the schema ranks after it, and takes its neighbours' indentation. A hand-kept
table would copy 671 orders from a schema and then drift from it. The tests prove the
placement the strict way: undoing seven mutations by patch gives back the original invoice
byte for byte, including the whitespace.

**3. "The guard goes by element names. What does it refuse that it should not, and what does
it let through?"**

It errs towards a person. It refuses fixes a person would accept at once, such as a unit code
`SAT` replaced by `HUR` (a quantity's unit is what the price is per) or the seller's VAT
status. They come back as decisions, with the patch and its reason, so nothing is lost. It lets
through changes that matter but do not move money, tax, a party or a date: the type code, a
payment reference, an order reference. Those are applied, but never without a person's
approval, and the loop of the next branch will check the values a model writes, as ADR-0022
checks an explanation's. The guard also looks wider than the place it changes: at every element
above it, and for a removal at everything the element holds. Removing an invoice line removes
amounts, so it is refused.

## The one concept to explain unaided

**A patch touches more than it changes.** It touches its place, what that place is inside of,
and, for a removal, what it holds. The guard checks all three before anything changes, and every
step of a patch is checked before the first one is made, so a refused or failed patch leaves the
invoice exactly as it was.

## Supporting facts worth remembering

- Modules: `places` (the grammar), `schema_order` (the XSDs), `guard`, `patches` (`Patch`,
  `Outcome`, `apply`), `repair` (validate again, diff); `einvoice patch` exits with 0 only when
  every patch applied and the invoice is valid.
- No patch leaves an element empty: Peppol refuses one (`PEPPOL-EN16931-R008`). So an
  aggregate is added only with a basic component inside it, and an aggregate a removal empties
  goes with it.
- Limits: 100 patches, 1 000 characters for a path and for a value, positions of six digits,
  characters XML allows. A repair of a small invoice takes 11 ms warm, validation included.
- The diff compares copies indented alike, so a one-line invoice diffs as clearly as an
  indented one; its line numbers count lines of those copies.
