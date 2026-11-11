# 62. Invoices are read from PDFs and pictures into fields a person confirms, and code writes the UBL

- Status: accepted
- Date: 2026-11-11
- Deciders: the team (milestone M7)
- Technical story: milestone M7, branch `feat/api-invoice-extraction`; the brief's "PDF → UBL
  extraction with a review step, clearly marked beta", widened to pictures at the maintainer's
  request of 2026-11-08 ("most people will send a PDF or a picture"), and kept free: the model
  is on Groq's free tier

## Context and problem statement

SEF takes UBL. Most of the people the product is for do not have UBL: they have the PDF an ERP
printed, or a photograph of a paper invoice. Reading those into an invoice is the most useful
thing the product can add, and the one where a language model is most tempting to trust: it can
read a page and write UBL in one go. It would also get an amount, a PIB or a date wrong now and
then, silently, in a document whose job is to be exact. How is an invoice read from a PDF or a
picture so that the product stays what the brief says, a model between deterministic walls?

## Decision drivers

- The model is never trusted (the brief's architecture): what it reads is checked by a person
  and judged by the validator, and nothing it writes leaves without both.
- No invoice content stored or logged; a photograph's metadata never sent anywhere.
- Free: a model on Groq's free tier, the libraries already in the lock.
- Hostile input: a PDF or a picture is a parser's attack surface.
- Measurable: the reading can be put through the evaluations, as the explanations and repairs
  are (M6).

## Considered options

1. **The model reads a document into fields; a person confirms them; code writes the UBL; the
   validator judges it.** Chosen.
2. The model writes the UBL directly.
3. OCR (Tesseract) and rules, without a model.

## Decision outcome

**Two steps, a person between them.** `POST /invoices/extract` reads a document into an
invoice's fields with a model and answers them; nothing is stored. The person compares the
fields with the document and corrects them. `POST /invoices/draft` writes the UBL invoice those
fields describe, in code; the endpoints of `/invoices` then validate, store, explain, repair and
send it as any other. Both are beta, and say so.

**The fields, not UBL** (`sef_api.extraction.fields`). The business terms of EN 16931 that a
Serbian invoice prints, in its plain form: the parties' names, PIB, registration number and
address, the dates, the lines, the VAT recapitulation, the totals, the bank account and the
payment reference, and whether the seller is in the VAT register. Every value is text or null,
in a form the model can check (`2026-10-05`, `14400.00`); their JSON schema is made from the
models for structured outputs in strict mode. The model is told to write what the page shows and
nothing more: no amount computed, no field guessed. An answer of the wrong form goes back with
what is wrong, at most three times, as the explainer's and the repairer's do.

**The UBL in code** (`sef_api.extraction.draft`). Deterministic: every element comes from a
field, or from SRB-CIUS where the profile fixes it (the specification identifier, the payment
means, the PIB as an electronic address and a VAT identifier, `(mod97)` before a reference with
a model, the VAT point code). Nothing is computed or filled in: a field left empty leaves its
element out, and the validator reports it. A type code 381 is written as a credit note.

**The documents** (`sef_api.extraction.documents`). A PDF of at most three pages, or a JPEG, PNG
or WebP picture, read in chunks within `SEF_MAX_DOCUMENT_BYTES`. What it is comes from its first
bytes, which must agree with its media type. A PDF is opened by PDFium (`pypdfium2`), which runs
no script and fetches nothing; each page is drawn at 1600 pixels on its longer side, and its
text layer kept, since a model reads given characters more surely than drawn ones. A picture is
opened by Pillow, for those three formats only, refused above 40 million pixels before it is
decoded, turned upright by its EXIF orientation and encoded anew as JPEG, which leaves its
metadata behind. PDFium serves one thread at a time: one lock, a worker thread.

**The model.** A message may carry pictures (chat completions as data URLs, Anthropic as base64
blocks). Each provider names its reading model: on Groq, `qwen/qwen3.8-27b`, which reads pictures
and keeps structured outputs in strict mode on the free tier, since the default GPT-OSS models
read none; OpenAI's and Anthropic's defaults read pictures. `SEF_EXTRACTION_MODEL` names another.
An organization with its own key (ADR-0058) is read by its provider's reading model, with its
key, whatever model it chose to write.

### Consequences

Good:

- A misread value is caught twice: by the person, who sees the page beside the fields, and by
  the validator, whose arithmetic rules catch totals that do not add up.
- The model cannot write a UBL element, an extension or a namespace: only fields of a fixed form.
- A document's text may say anything, an instruction to the model included; all it can change
  is fields that a person reviews and the validator checks.
- The fields are measurable against known invoices (`fields_of`), for the evaluations.

Bad / accepted:

- Beta. Advance settlements (the Serbian extension), the VAT in dinars of an invoice in another
  currency, a credit note's reference to the invoice it corrects and the codes of VAT exemptions
  are not read: the validator reports them, and a person adds them.
- Three pages at most, as many pictures as Groq's reading model takes at once.
- Pictures cost tokens: on Groq's free tier, a reading or two a minute.

## Pros and cons of the options

### The model writes the UBL directly

- Good: one step, no field model.
- Bad: the model would decide structure, namespaces and codes the profile fixes, and could add
  any element; a person cannot review UBL as they review a form.

### OCR and rules

- Good: deterministic, no model.
- Bad: invoices have no common layout; rules per layout do not scale, and Tesseract reads a
  photograph's skew and shadows poorly. A model reads layouts it has never seen; the person and
  the validator make up for its being a model.
