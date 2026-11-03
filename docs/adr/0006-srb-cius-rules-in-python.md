# 6. SRB-CIUS rules: authored in Python, one rule per module, each cited and tested

- Status: accepted
- Date: 2026-11-04
- Deciders: Marko Spasojević
- Technical story: milestone M1, branch `feat/core-srb-cius-rules`

## Context and problem statement

SEF accepts invoices that follow SRB-CIUS, the Ministry of Finance's core invoice usage
specification of EN 16931 for domestic invoices (version of 06.06.2025). Unlike EN 16931 and
Peppol BIS, it is published as a document, not as rules: a table of the EN 16931 business
terms with Serbian usage notes, cardinalities tightened by striking out the EN 16931 value and
writing the new one beside it, an extension table, and code lists issued separately (VAT
categories and exemption codes). There is no Schematron and there are no rule identifiers.
The third wall of the deterministic validator (ADR-0002) therefore has to be written by us.
We had to decide in what form, how a rule is identified and cited, what a rule may judge, and
how we show that a rule says what the specification says and nothing more.

## Decision drivers

- Traceability: every violation must lead to the passage and the version of the document it
  comes from, because the explainer may only cite what the validator points to (ADR-0002).
- Precision before coverage: a false "SEF will reject this" blocks a legitimate invoice, since
  nothing leaves without a green validator; a requirement we cannot justify from the text must
  not be fatal.
- Review: a rule must be readable next to its passage, and adding one must not touch others.
- The same violation model and locations as the other layers (ADR-0003, ADR-0004, ADR-0005).
- Budget (brief §5): < 500 ms warm for all layers together.

## Considered options

1. **Python rules, one per module, discovered by name, each a `Rule` with metadata and a
   `check(document)` generator** — chosen.
2. Our own Schematron, executed by the existing Saxon pipeline (ADR-0005).
3. A declarative rule file (YAML or JSON: path, cardinality, pattern, code list) interpreted by
   a generic engine.
4. The EN 16931 Schematron edited to include the Serbian restrictions.

## Decision outcome

Option 1. Concretely:

- **Shape.** `einvoice_core.srb.rule.Rule` is data plus one function: `id`, `title`, `terms`
  (the business terms and groups concerned), `references` (document key and passage),
  `severity` and `check(document)`, which yields a `Finding` — a message and the element, and
  if needed the attribute, it is about. `validate_srb` turns findings into violations with
  `layer = "srb-cius"`, the canonical XPath and the source line; messages begin with
  `[SRB-NNN]-`, as EN 16931 messages begin with their rule id.
- **One module per rule.** `srb/rules/srb_NNN_<subject>.py` defines `RULE`. The loader imports
  every module whose name matches and refuses one without a rule or whose rule id differs from
  its name. Shared XPaths live in `srb/paths.py`, permitted values with their passage in
  `srb/codes.py`, identifier arithmetic in `srb/identifiers.py`.
- **Identifiers.** `SRB-001` upwards, in authoring order. Once released, an id is never reused
  or renumbered; a rule whose meaning changes gets a new id and the old one is retired in the
  changelog.
- **Sources.** `srb/sources.py` records every official document a rule cites, with its
  version or Official Gazette issues and its URL. A reference names a document by key and a
  passage (`1.3, Table 1, BT-31`); a test refuses a rule without references or with an unknown
  document.
- **What a rule reads.** The typed model where it carries the business term, the lxml tree for
  syntax the model does not keep (`schemeID`, the tax scheme a registration is filed under).
  Like Schematron, the rules run only on schema-valid documents.
- **What a rule may judge.** Only what the text states. A note that restates an EN 16931 rule
  is not repeated (the Schematron layer reports it). Where a note depends on a fact the
  invoice does not state, the rule says how it decides: residency is read from the party's
  country code `RS`. Identifiers are checked strictly on form (ASCII digits, exact lengths),
  and arithmetically only where a regulation we cite defines the arithmetic: the PIB's serial
  range and ISO 7064 MOD 11,10 check digit (PIB rulebook, Article 2), not the JMBG's check
  digit, which the rulebook does not define. Form and arithmetic are separate rules (SRB-007
  and SRB-008, SRB-009), so a wrong last digit is explained as the typo it usually is.
- **Severity.** A requirement the specification states is `fatal`. It is a `warning` when the
  example documents published with the specification contradict it, or when the text leaves it
  open; the rule's docstring names the evidence, and the work against the SEF demo environment
  (M5) confirms or changes the severity. The example documents are evidence about how SEF
  reads the text, the text is what the rules implement.
- **Proof.** Every rule module has a test module with at least one `test_satisfied_*` and one
  `test_broken_*` (a meta-test enforces it). Tests edit one valid synthetic invoice, so each
  broken case differs from a valid document by one change, and assert the message and the
  XPath. The synthetic Serbian invoices must satisfy every rule.

### Checked against the official examples

The Ministry publishes 17 example documents with the specification (invoices, credit and debit
notes, advance and final invoices, foreign currency, public procurement, fiscal receipts). Run
locally (they become fixtures in `feat/core-fixtures-corpus`): SRB-001 to SRB-008 report
nothing; SRB-009 reports exactly the four placeholder PIBs `123456789` and `987654321` in each
document; one example is not schema-valid, because its embedded PDF is abbreviated with `...`,
so the rules do not run on it. The same run showed that the EN 16931 rules reject eight of the
sixteen schema-valid examples: the Serbian VAT categories and exemption codes are not in EN 16931's code lists,
category `O` appears next to `S`, the RSD copy of the VAT breakdown in a foreign-currency
invoice is summed as if it were in the invoice currency, the totals a final invoice repeats in
the Serbian extension are checked as invoice totals, and one allowance has no reason. That is a
matter for the SRB profile of the validation pipeline, not for these rules (learning note 04).

### Measured (container, Python 3.12)

- Nine rules: 0.3–0.4 ms per invoice warm (4–11 KB); ~2 ms including the typed model.

### Consequences

Good:

- A reviewer reads one short file per rule next to one passage; a new rule changes no other
  file.
- Violations carry the rule id, the passage and the document version, ready for citations
  (M2).
- Conditions across the document, code lists and identifier arithmetic need no DSL, and the
  rules are type-checked.
- Negligible in the performance budget.

Bad / accepted:

- Rules are code: they need code review and tests, and a non-programmer cannot add one. The
  uniform shape and the per-rule tests keep the cost low.
- `SRB-NNN` means nothing to SEF or to other tools; the references carry the link to the
  source.
- A new version of the specification means rechecking every rule's passage by hand; the
  source registry pins the version, so the upgrade is a visible change.
- While a contradicted requirement is a warning, an invoice SEF rejects can pass; the warning
  names the requirement, and M5 settles it.

## Pros and cons of the options

### Our own Schematron

- Good: the same engine as EN 16931 and Peppol; Schematron is the usual medium for business
  rules and could be shared with other tools.
- Bad: XPath 2.0 assertions are harder to review and to test one by one; code lists and PIB
  arithmetic become XSLT functions; we would maintain a compiled stylesheet of our own source.
  Nothing in the specification needs what Schematron is good at.

### Declarative rule file

- Good: rules as data, a generic engine, an easy catalogue.
- Bad: the notes are conditional ("for residents", "on advance invoices", "when BT-8 is 35"),
  refer to other fields and to code lists; the format would grow conditions and expressions
  until it is a worse programming language, with errors found at run time instead of by the
  type checker.

### Edited EN 16931 Schematron

- Bad: third-party rule sets are never modified (ADR-0005), and one file with two authorities
  could no longer say whose rule a violation is.
