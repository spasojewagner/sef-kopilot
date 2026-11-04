# M1 — `feat/core-fixtures-corpus`

## Three questions a senior engineer would ask

**1. "You committed the Ministry's example invoices but not CEN's or OpenPeppol's. Why the
difference?"**

Licences. Official materials of a Serbian state body are not copyright works (Law on Copyright
and Related Rights, Article 6), so the 17 examples can live in the repository — byte for byte,
with the page, the URL and the SHA-256 of each file in a manifest that a test checks. CEN's and
OpenPeppol's artefacts come with their own terms (OpenPeppol's repository ships no licence
file at all), so they are fetched at a pinned version and used from `third_party/`, never
copied. The SEF files keep their CRLF line endings because `.gitattributes` stores them
unnormalised; otherwise a checkout would no longer match the digests.

**2. "Isn't a golden file brittle? Won't every change break the build?"**

Only a changed verdict breaks it, and that is exactly what should be reviewed. The file
records validity and how often each rule was reported or set aside — not messages or line
numbers — so rewording a message or reformatting a document changes nothing. When behaviour
changes on purpose, `make fixtures` rewrites the file and the diff shows which documents
changed and how; reviewing that diff is the approval.

**3. "Why generate the invalid invoices from a catalogue instead of writing them by hand?"**

A hand-written invalid file loses its meaning: months later nobody knows which mistake it was
meant to show, and nobody notices when a rule change makes it report something else. Each
catalogue entry states the mistake and the rules that must be reported; the generator writes
both into the file's header; the tests check the report and that the files are what the
generator writes. Every edit must match its base exactly once, so a changed base fails loudly
instead of quietly producing a different document.

## The one concept to explain unaided

**Intent versus observation.** The catalogue's expectations are intent: written by a person,
for the cases someone thought of ("a PIB typo must produce SRB-009 twice"). The verdicts file
is observation: written by the machine and approved by a person in review, covering every
document, including those nobody wrote an expectation for. Intent catches wrong behaviour;
observation catches any change. A useful corpus has both.

## Supporting facts worth remembering

- 93 documents with recorded verdicts: 17 SEF examples, 4 synthetic bases, 43 mutations, 19
  CEN and 10 OpenPeppol examples; with the 1 471 official unit-test documents run against the
  Schematron layer, over 1 500 in all.
- With valid check digits for their placeholder PIBs, 15 of the 17 SEF examples are valid under
  `srb`; under plain EN 16931, 9 are invalid, 7 of them only for what SRB-CIUS widens.
- Found while building it: BR-CO-25 is not in CEN's UBL Schematron, and CEN's BR-53 is
  satisfied by the RSD totals inside the Serbian extension (`//cac:TaxTotal`).
