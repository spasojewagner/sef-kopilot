# 47. The rule catalogue is read from the rule sets the validator runs

- Status: accepted
- Date: 2026-11-08
- Deciders: the team (milestone M4)
- Technical story: milestone M4, branch `feat/core-rule-catalogue`, for `search_rules`
  (`feat/mcp-search-rules`); the guardrail that third-party rule sets are fetched, never
  modified and never committed

## Context and problem statement

A report names the rules an invoice breaks. An assistant helping a person write an invoice, or
answering "what does BR-CO-15 require?", needs the rules it has not broken too: every rule a
profile applies, by its id or its subject. Where should that list come from, so that it says
what the validator checks, in the words a violation of it would use?

## Decision drivers

- One list: a rule the validator reports is in the catalogue, and nothing else is.
- The rule sets are fetched under their own licences, never modified, never committed.
- The calculation rules and the set-asides are this project's decisions (ADR-0007, ADR-0008)
  and must read as they apply.
- Cheap: read once per process, searched in memory.

## Considered options

1. **Read at run time from the rule sets the profile runs**, with the arithmetic and SRB-CIUS
   rules from the code. Chosen.
2. A catalogue generated once and committed, as JSON.
3. No catalogue: the rules a report names, and the corpus for the rest.

## Decision outcome

**Read from the published rule sets.** `catalogue(profile)` parses each rule set the profile
runs as data: the assertions of Peppol's Schematron sources (`assert`, `report`, their id and
flag as attributes) and of CEN's compiled XSLT (`svrl:failed-assert`, its id and flag as
`xsl:attribute`), with each statement as its violation's text, the `[ID]-` before it taken
off. A rule's first assertion states it. An assertion without a flag is fatal, as the validator
reads a report. Then:

- the calculation rules are the arithmetic layer's statements, which replace CEN's under the
  same ids;
- for `srb`, the SRB-CIUS rules are added with their titles and business terms;
- a rule the profile sets aside whatever the document holds says why, and what checks the
  matter instead; one set aside only in some places of a document is listed as it is.

**Searched by id, term, then words.** An exact id, then ids it begins (`BR-CO`), then rules that
concern a business term it names (`BT-31`), then rules whose statement holds every word of it,
case and diacritics aside; in each, the Serbian rules first, as the most specific where they
apply.

A test validates every fixture and official example under every profile and asks that every
rule reported, kept or set aside, is in that profile's catalogue.

### Consequences

Good:

- The catalogue cannot drift from the validator: a new edition of a rule set brings its own
  rules and words.
- Nothing of a rule set is copied into the repository.

Bad / accepted:

- Without fetched rule sets there is no catalogue, as there is no validation.
- The statements are English, as the rule sets publish them; the SRB-CIUS titles are ours, in
  English too. Explanations in Serbian remain the explainer's.
- The three catalogues take about a tenth of a second to read, once per process.

## Pros and cons of the options

### Generated once and committed

- Good: no parsing at run time.
- Bad: a copy of licensed rule texts in the repository, against the rule of `third_party/`, and
  one more thing to regenerate with every edition.

### No catalogue

- Good: nothing new.
- Bad: "which rules concern the seller's PIB?" has no answer before an invoice breaks one.
