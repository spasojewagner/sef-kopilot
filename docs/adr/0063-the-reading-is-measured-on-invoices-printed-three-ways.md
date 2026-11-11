# 63. The reading is measured on invoices printed three ways, by field, against thresholds

- Status: accepted
- Date: 2026-11-11
- Deciders: the team (milestone M7)
- Technical story: milestone M7, branch `feat/evals-extraction`; ADR-0062 reads invoices from
  PDFs and pictures and promises that the reading is measurable; ADR-0054 and ADR-0055 set how
  the model is measured, offline, against thresholds that gate CI

## Context and problem statement

The reading model now turns a PDF or a photograph into an invoice's fields (ADR-0062). A person
checks them, and the validator judges the invoice made of them, but how often does the person
have to correct something, and does the reading ever fill in what a document does not say?
Without numbers, a change of model, prompt or picture size is a guess. What is measured, on
what documents, and how are the model's answers to pictures replayed offline, as the
explanations' and the repairs' are?

## Decision drivers

- No real invoice, ever, even anonymised (the brief): the documents must be synthetic.
- Documents as people have them: a PDF from a business program, a scan, a phone's photograph.
- A measure a person can act on: which field, of which document, was read wrong.
- The brief's guardrail, here: the model must not guess what a document leaves out.
- Offline in CI, as the other evaluations (ADR-0055): the answers recorded once, on a free tier.
- Recorded on the maintainer's Windows machine, replayed on Linux in CI.

## Considered options

1. **Synthetic invoices by their fields, printed three ways from HTML; measured field by field,
   per form, with a rate of invented fields and a share of valid invoices.** Chosen.
2. The synthetic UBL fixtures rendered to PDF, measured against `fields_of` their XML.
3. One end-to-end measure: documents whose reading makes a valid invoice.

## Decision outcome

**The golden set is fields, printed.** `evals/golden/extraction.yaml` names ten invoices by the
fields they print, in the form of the API's `InvoiceFields`, varied as invoices are (one line
or twelve, two VAT rates, an advance invoice and a debit note, a Cyrillic seller, millions,
empty fields). `scripts/render_documents.py` prints each with Chromium in one of two layouts as
a PDF with its text, a scan (a grey picture in a PDF without text) and a photograph (turned,
lit unevenly, soft), with fixed seeds; the thirty documents are committed. The tests check that
every case's fields make an invoice the validator accepts, so a reading that does not is the
reading's fault, and that the documents open as the API opens an upload.

**Measured by field, and by what was not there.**

- `extraction_pdf`, `extraction_scan`, `extraction_photo`: of the fields an invoice has, the
  share read as it has them, per form. Amounts are compared as numbers, text with its spaces
  collapsed; a line missed counts each of its fields.
- `extraction_invented`: of the fields an invoice leaves empty, the share the reading filled in,
  the fields of a line it made up among them.
- `extraction_valid`: the documents whose fields, as read, make an invoice the validator
  accepts: how often the review has nothing to correct.

The thresholds (97 %, 95 %, 90 %; at most 5 % invented; 60 % valid) were set before the first
recording, as the floor the beta must clear, from what a document gives: a PDF its text, a scan
and a photograph their pixels alone. A first recording below one is a finding about the reading,
not a reason to lower the threshold unexamined.

**Pictures are named by their documents in a cassette's key.** A request is named by the
SHA-256 of what is sent (ADR-0055). A page's picture is drawn by PDFium or Pillow, whose
results may differ in their last bits between platforms; keyed by its bytes, a picture recorded
on Windows would find no answer on Linux. The evaluations name each picture by the document it
was drawn from: the file's SHA-256, the page, the picture's size and its JPEG quality. A
changed document, page size or quality is a new request; the same document drawn on another
machine is the same one. A message without pictures keeps the key it always had, so the
cassettes recorded before stay valid. The reading is recorded with the provider's reading model,
forty-five seconds apart, under Groq's free tier's tokens a minute.

### Consequences

Good:

- A regression names its document and field: "`server-equipment.jpg`: `lines[1].unit_price`
  read as `'124990.00'`, the invoice has `'1249900.00'`".
- Guessing is measured apart from misreading, so a model that fills in a missing date to look
  complete is caught even when its other fields are right.
- The forms are measured apart: a change that helps PDFs and hurts photographs shows as such.
- A cassette recorded on any machine replays on any other.

Bad / accepted:

- Synthetic documents are cleaner than real ones: no stamps, no handwriting, no creases, one
  page. The photographs are simulated. The measures are an upper bound on real documents, and
  say so.
- Thirty documents (about 3 MB) are committed, as the evaluations replay answers to them.
- Naming a picture by its document trusts that drawing it differs only in its last bits; a
  change to how documents are drawn that keeps their size must be recorded again on purpose.
- Ten invoices, some 570 fields a form, are enough to catch a regression, not to rank two good
  models.

## Pros and cons of the options

### The synthetic UBL fixtures, rendered

- Good: one source of truth with the validator's fixtures; `fields_of` gives the fields.
- Bad: there are five, too few and too alike; and fields a PDF prints but the XML does not carry
  (the payment model, the VAT status as printed) would not be measured.

### One end-to-end measure

- Good: one number: how often the reading needs no correction.
- Bad: it says neither which field nor whether the model guessed; a misread matični broj, which
  carries no check digit the validator could test, passes the validator and the measure both.
