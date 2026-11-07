# M4 — `feat/web-upload-picture-or-pdf`

## Three questions a senior engineer would ask

**1. "Why not take the picture and let the model read the invoice off it?"**

Because the invoice is the XML that goes to SEF, and the picture only shows some of it. Reading
values off a picture is the model deciding amounts, tax numbers and dates, which the guardrails
forbid; a green verdict would then vouch for what the model read, not for the invoice. Half of
what SRB-CIUS checks is not on the picture at all: the VAT category codes, the reason for an
exemption, the unit codes. Turning a PDF or a picture into an e-invoice is planned as a step of
its own, a draft whose every value a person confirms, marked beta, after the evaluations that
can measure how often the model reads a field right (M7).

**2. "Why check in the browser rather than on the server?"**

The point is that the file never leaves the device. A picture may be of a real invoice, and the
public demo stores what it receives and sends parts of it to the language model's provider. The
server stays the judge of whatever reaches it: a picture renamed and sent as XML is reported as
not well-formed there, as before. The browser's check only spares a useless, perhaps harmful,
upload.

**3. "Media type, file name or the first bytes: how do you tell what a file is?"**

The browser's media type, which it takes from the file's name on the device, or else the name
itself. It is a courtesy, not a security check, so a good guess is enough. Reading the file's
first bytes, its signature, would also catch a PDF named `.xml`, but it means reading the file
before sending, and the validator already catches that case.

## The one concept to explain unaided

**A rendering is not the document**: an e-invoice is structured data with a legal meaning; its
PDF or its picture is one view of part of it, made for people.

## Supporting facts worth remembering

- The file picker's `accept` only suggests: a person may choose any file in the dialog.
- The message says what to do next, where to get the XML (SEF, or the program that issued the
  invoice), and that nothing was sent.
