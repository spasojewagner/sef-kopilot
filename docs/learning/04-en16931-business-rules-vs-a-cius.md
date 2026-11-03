# EN 16931 business rules vs. a CIUS

EN 16931-1 defines one semantic model of an invoice — business terms (`BT-n`) in groups
(`BG-n`) — and the business rules that keep it consistent: `BR-n` for presence and structure,
`BR-CO-n` for calculations, `BR-CL-n` for code lists, `BR-S-n`, `BR-E-n`, … per VAT category.
Countries and networks adapt the model, and CEN allows exactly two kinds of adaptation.

## Two ways to adapt the model

| | CIUS (core invoice usage specification) | Extension |
| --- | --- | --- |
| May | make optional terms mandatory or forbid them, narrow cardinalities, restrict code lists and values, add usage notes | add terms the core model does not have |
| May not | add terms or codes, contradict a core rule | — |
| Result | every conforming invoice is still an EN 16931 invoice | the invoice is *conformant*, not *compliant* |
| BT-24 | `urn:cen.eu:en16931:2017#compliant#<cius>` | `…#conformant#<extension>` |

SRB-CIUS is both. `urn:cen.eu:en16931:2017#compliant#urn:mfin.gov.rs:srbdt:2022` names the
CIUS; `…#conformant#urn:mfin.gov.rs:srbdtext:2022` says the Serbian extension (advance
payments used and RSD amounts, in `ext:UBLExtensions` under `http://mfin.gov.rs/srbdt/srbdtext`)
may appear. Peppol BIS Billing 3.0 is a CIUS as well, published as Schematron
(`PEPPOL-EN16931-R001` …).

## How SRB-CIUS writes its restrictions

One table row per business term, in Serbian, with:

- **the cardinality**: where Serbia tightens it, the EN 16931 value is struck through and the
  new one written beside it — seller VAT identifier BT-31: ~~0..1~~ 1..1. Text extraction
  drops the strike line, so the 18 tightened values were found by reading the PDF's drawing
  layer, not the text;
- **a usage note**: "for public-funds users exactly one identifier `JBKJS:` followed by five
  digits", "mandatory for residents", "on an advance invoice, code 432 means the payment date";
- **no rule ids and no Schematron**. The rules in `einvoice_core.srb` are our reading of the
  notes, each citing its row and the document version (ADR-0006).

## What a validator has to do with that

1. In theory an SRB invoice satisfies EN 16931 (a CIUS only narrows it) plus the SRB rules:
   run both and report the union.
2. In practice SRB-CIUS also *widens* EN 16931 in places. It adds VAT categories (`R`, `OE`,
   `SS`, `N`) and exemption codes (`PDV-RS-…`) that EN 16931's code lists lack, uses category
   `O` together with `S`, which EN 16931 forbids, and carries an RSD copy of the VAT breakdown.
   Run against the examples SEF publishes, EN 16931 rules `BR-CL-17`, `BR-CL-18`, `BR-CL-22`,
   `BR-O-*`, `BR-S-08`, `BR-CO-10` and `BR-CO-13` fail on eight of the sixteen schema-valid
   documents.
3. So the SRB profile cannot run EN 16931 unchanged: it must set aside the EN 16931 rules the
   Serbian rules replace — listed, each with its reason — or every correct Serbian invoice with
   an exemption code is "invalid". That list belongs to the validation pipeline
   (`feat/core-cli`), not to the rule sets, which are never edited.

## The text and the examples

The examples published with the specification are illustrations, not test cases: their PIBs
(`123456789`, `987654321`) fail the check digit, one embeds an attachment abbreviated with
`...`, and some omit elements the table makes mandatory. The text is what the rules implement;
the examples are evidence about how SEF reads it. Where the two disagree, the rule reports a
warning and says why, until the SEF demo environment settles the question (M5).

## Check yourself

- Why may a CIUS make BT-31 mandatory, but not add a VAT category?
- What does `#compliant#` versus `#conformant#` in BT-24 tell the receiver?
- Why does `BR-CL-22` fail on a correct Serbian invoice, and which component decides to set it
  aside?
