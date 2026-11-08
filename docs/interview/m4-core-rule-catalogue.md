# M4 — `feat/core-rule-catalogue`

## Three questions a senior engineer would ask

**1. "Why parse XSLT at run time instead of keeping a list of rules?"**

Because a kept list drifts from what the validator runs, and copying the rule texts would put
licensed third-party material in the repository, which `third_party/` exists to avoid. The
validator runs the published rule sets; the catalogue reads the same files as data, so it says
what is checked, in the words a violation of it uses. A test validates every fixture and
official example under every profile and requires every rule reported to be in the catalogue.

**2. "CEN's BR-CO-15 is in the XSLT too. Which one does the catalogue list?"**

The arithmetic layer's: it recomputes the calculation rules under CEN's ids and sets CEN's
aside (ADR-0007), so that is the rule a person meets in a report. A set-aside that applies
whatever the document holds is shown with its reason and the rule that checks the matter
instead (`UBL-CR-001` → `SRB-029`); one that applies only in some places is not, since the rule
still applies elsewhere.

**3. "How do you order search results?"**

An exact id, then ids it begins, then a business term it names, then words, all of them, with
diacritics folded so that `placanja` finds `plaćanja`. Within each, the Serbian rules first:
under the `srb` profile they are the most specific answer to "which rules concern BT-31?".

## The one concept to explain unaided

**Read the source of truth as data**: when a system already runs from a published artefact,
derive the descriptions from that artefact rather than maintaining a second copy.

## Supporting facts worth remembering

- About 1 000 rules for `srb` and `en16931`, 1 100 for `peppol`; read in a tenth of a second,
  once per process.
- A seeded fault showed that ordering ids by their numbers changed nothing, since the published
  ids are padded (`BR-01`, `SRB-001`); the plain order stayed.
