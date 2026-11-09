# M6 — `feat/evals-harness`

## Three questions a senior engineer would ask

**1. "Your validator is deterministic and tested. What does an evaluation add?"**

A number a reader can check, and a gate that a change can fail. The tests say each piece does
what it was written to do; the evaluations say how well the whole does its job, on every
document of the corpus: the same verdicts as the published rule sets applied as published, no
invoice let through that must be refused, every mistake reported by its rule. The first run
proved the point: it found two of the Ministry's examples rejected for their own flaws besides
the placeholder PIBs, a label I had written wrong, not a defect the tests could see.

**2. "Where do the labels come from? If from the validator, the 100 % is circular."**

Never from the validator. CEN's and OpenPeppol's examples are published as valid; the Ministry's
carry placeholder PIBs; each mutation was made to have one mistake, which its header states
before any validator ran on it. `verdicts.json` records what the validator says, and the tests
hold it there; the golden set says what it must say, and the evaluations compare the two. A
test keeps the golden set covering the whole corpus.

**3. "Which reference? There is no SRB-CIUS validator to compare with."**

For EN 16931 and Peppol, the published artefacts in the order a reference validator applies
them: the UBL 2.1 schema, then the Schematron, nothing set aside. The validator deliberately
differs from that (Serbian set-asides, the calculation rules in Python), so agreement proves
those choices change no verdict. For SRB-CIUS there is none; the golden labels carry it, and
the documents are still compared under EN 16931, which SRB-CIUS restricts.

## The one concept to explain unaided

**A measure is only as good as its labels**: the expected answers must come from outside the
system under test, or the measure only says the system agrees with itself; and every number
must name the cases behind it, so that a miss leads to a document, not a shrug.

## Supporting facts worth remembering

- 93 documents compared with the reference, 56 that must be rejected, 38 that must be
  accepted, 60 whose mistake must be reported by named rules; all thresholds met.
- The report is deterministic (no time, no machine), committed, and checked by `make
  evals-check` like a generated file; a run takes about three seconds.
- Seeded faults in the validator (SRB-009 blind, BR-CO-16 never reported, BR-06 set aside, CEN's
  calculations kept twice, the schema skipped) each fail the evaluations.
