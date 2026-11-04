# 14. Hostile documents in the core: linear addressing, bounded numbers and reports, whole values, a silent Saxon

- Status: accepted
- Date: 2026-11-04
- Deciders: Marko Spasojević
- Technical story: milestone M2, branch `fix/core-hostile-documents`, found by two reviews of
  `feat/api-invoices-validate`

## Context and problem statement

The API is about to validate documents sent by anyone with an account. Two security reviews of
that branch measured five problems in the validator itself, each reachable with a document well
under the API's size limit:

1. **Quadratic addressing.** `canonical_xpath` found an element's position by reading all of
   its same-named siblings. The parser addresses every invoice line, price and VAT category,
   and the Schematron layer resolved every SVRL location step by step in the same way. An
   invoice of 8000 lines took 39 s; one with 8000 empty document references (each failing
   BR-52) took 73 s, at 600 KiB.
2. **Unbounded numbers.** `xs:decimal` has no limit on digits. Python's default decimal
   context keeps 28 and rounds beyond them. Rounding an amount of 10^27 to cents raised
   `InvalidOperation`, so the pipeline raised under every profile, and longer sums were
   rounded silently. CEN's rules, run by Saxon, compute with arbitrary precision.
3. **Saxon's error stream.** Saxon writes warnings to the process's standard error, and a
   dynamic error in a rule set's match pattern is a warning that quotes the value it met: a
   seller with two VAT identifiers makes the Peppol rules print their country prefix. That
   is invoice content in a service's logs, beyond the reach of any Python log handler.
4. **Values split by comments.** XML lets a comment or a processing instruction sit inside a
   value: `<cbc:PayableAmount>14400<!-- -->1</cbc:PayableAmount>` is 144001 to the schema and
   to CEN's rules. The parser kept both, so the value was two text nodes, and the model and
   the SRB rules read `element.text`, which stops at the comment. The arithmetic layer, which
   checks CEN's calculation rules in their place, saw 14400, and an invoice due ten times its
   total was valid under the SRB and EN 16931 profiles. The Peppol rules read `text()` in 22
   places; a split customization identifier stopped them with an error.
5. **An unbounded report.** The report listed at most `max_violations` violations but every
   set-aside one. A document of 144 KB with 8000 empty elements in an extension made 16 005
   set-aside reports, and a report of 7.6 MB.

How should the core address elements, which numbers should it accept, what is a value, how
large may a report be, and where should Saxon's output go?

## Decision drivers

- A schema-valid document must yield a report, never an exception (ADR-0008).
- The checks must be exact, as CEN's are (ADR-0007), and read the same values as the schema and
  the published rule sets.
- No invoice content in logs or traces (brief, guardrails).
- Published rule sets are executed as published (ADR-0005).
- The work and the answer for one document are bounded by its size and the limits.
- Keep the parser's thirty call sites of `canonical_xpath` as they are.

## Considered options

For addressing:

1. **An index of each element's children, scoped to a block (`sibling_index()`), held in a
   context variable and opened by the pipeline and each layer's entry point.** Chosen.
2. An index object passed explicitly to every function that addresses elements.
3. lxml's `getpath()`, in C.
4. The positions of every element of the document, computed once up front.

For numbers:

1. **At most 28 digits in the model (a `MODEL` violation beyond), and the checks in a decimal
   context of 128 digits.** Chosen.
2. A higher precision only.
3. Catching `ArithmeticError` in the pipeline.

For values:

1. **The parser drops comments and processing instructions.** Chosen.
2. Every read takes the string value (`"".join(element.itertext())`), as XPath's `string()`.
3. A document with a comment inside a value is refused.

For the report:

1. **The set-aside list cut at the same limit as the violations, the rest counted.** Chosen.
2. A limit of its own for the set-aside list.
3. Set-aside violations counted, never listed.

For Saxon's output:

1. **A processor made from a configuration file that sends the error stream to the null
   device; without one where Saxon cannot open that device.** Chosen.
2. The configuration property set on the processor after it is made.
3. File descriptor 2 redirected around each Saxon call.
4. No validation at all where the null device cannot be opened.

## Decision outcome

**Addressing.** `sibling_index()` is a context manager and decorator in `einvoice_core.xml`.
Inside it, the first look at an element's children groups them by name and records each
one's place; later lookups reuse that. `canonical_xpath` and `child_element`, which the SVRL
resolver now uses, consult the index when one is open and compute afresh otherwise. The
pipeline and every layer's entry point open a block; nested blocks share the outer index,
and leaving the outermost one forgets it. Because the index lives in a context variable,
each thread has its own. The XPaths do not change, which a property test checks against the
plain computation. Another test counts the children each layer, and the pipeline, reads while
it addresses 300 lines: fewer than the document has elements, so a layer that loses its block
fails it.

**Numbers.** `einvoice_core.numbers` holds the rules:

- A number has at most 28 digits, not counting the leading zeros of its whole part. That is
  far beyond any real invoice.
- The parser reports a longer one as a `MODEL` violation naming the element, so the
  SRB-CIUS and arithmetic layers, which need the model, do not run.
- Those two layers compute inside `numbers.exact()`, a context of 128 digits, which holds the
  sum of any number of such values and the product of two of them exactly.
- Amounts in the Serbian extension, which the UBL schema does not validate, follow the same
  rules and so the form of `xs:decimal`, whose digits are 0 to 9 only: neither `1E3` nor
  `٨٤٠٠` is an amount, though `Decimal` reads the second as 8400.

**Values.** `load_document`'s parser drops comments and processing instructions
(`remove_comments`, `remove_pis`). Neither carries anything in UBL, and dropped they leave
every value one text node, which is how the model, the SRB rules and the published rule sets
read it. A test puts a comment or an instruction in the middle of every value of every
readable document of the corpus and checks that no verdict changes (87 of the 91 changed
before); another checks that the hidden amount above is reported under every profile.

**The report.** The set-aside list is cut at `max_violations`, like the violations, and the
rest is counted in `set_aside_omitted`; the 7.6 MB report is now 0.5 MB. Set-aside
violations are still never dropped silently, but no longer all listed: this amends ADR-0008.
Validity never depended on them. The command line counts them all and says how many it does
not list.

**Saxon.** Saxon reads its standard-error destination only from a configuration file, when
the processor is made. `_processor()` writes a one-line configuration
(`<global standardErrorOutputFile="…"/>` naming `os.devnull`) to a temporary directory,
makes the processor from it, and removes it. Errors still arrive as exceptions. A test
captures file descriptors 1 and 2 while a stylesheet meets a failing match pattern that
quotes the document. Saxon refuses the configuration when it cannot open the null device;
the processor is then made without it, and a log warning, which quotes nothing, says that
Saxon's warnings will reach the standard error. A test runs a process whose null device
cannot be opened.

### Consequences

Good:

- Measured: 8000 lines in 5 s instead of 39 s, and 8000 references in 22 s instead of 73 s.
- No schema-valid document makes the pipeline raise because of its numbers, and the checks
  are exact for every number the model accepts.
- Every layer, ours and the published ones, reads the same value, so a comment can neither
  hide a wrong amount nor fail a correct one.
- A report has at most twice `max_violations` entries, whatever the document.
- The validator writes nothing to the process's standard streams.

Bad / accepted:

- What remains of the 22 s is inside the published rule sets: their cost grows faster than
  linearly with the number of failing elements, and they cannot be changed. The 8000 empty
  extension elements above still take 15 s, nearly all of it in CEN's rules. Saxon also holds
  Python's GIL while it runs. A service has to bound both, which `feat/api-invoices-validate`
  does.
- The index holds the children of the elements it has visited until the block ends, and it
  must not be held across changes to the tree (the core never changes one).
- A document with a number of more than 28 digits is not checked by the Serbian and
  arithmetic layers. It is reported, not silently passed.
- A tree from `load_document` has no comments, so a document repaired from it (M4) loses the
  original's comments.
- Saxon's warnings are lost entirely, including any useful to a rule-set author; those are
  read with Saxon itself, outside the validator. Where the null device cannot be opened, they
  reach the standard error, as the log says; the API's child process (ADR-0015) does not
  start there at all, since it points its own standard streams at the same device.

## Pros and cons of the options

### An index object passed explicitly

- Good: no state outside the call.
- Bad: every helper of the parser gains a parameter it only passes on, and a forgotten one
  silently restores the quadratic cost.

### lxml's `getpath()`

- Good: written in C, so each call is much faster.
- Bad: still quadratic, and it writes the document's own prefixes, not the canonical ones.

### All positions up front

- Good: simple lookups.
- Bad: a proxy object for every element of the document, most of them never addressed.

### A higher precision only

- Bad: a million-digit amount is valid `xs:decimal` and breaks any fixed precision.

### Catching `ArithmeticError`

- Bad: it hides wrong results instead of preventing them, and still rounds silently below
  the point of failure.

### The string value at every read

- Good: the tree stays as it was sent.
- Bad: each of the eleven places that read a value has to remember it, and so does every
  future one; and it does nothing for the published rule sets, which read `text()`.

### Refusing comments inside values

- Bad: they are legal XML, the schema accepts them, and SEF has no such rule; a correct
  invoice would be refused for a reason of ours.

### A separate limit for the set-aside list

- Bad: a second setting to explain, for a list that never decides validity.

### Counting set-aside violations only

- Bad: the reasons the profile gives for setting a rule aside are the point of the list, and
  a document with a few of them should show them all.

### The property set after the processor is made

- Bad: measured to have no effect; Saxon has chosen its stream by then.

### Redirecting file descriptor 2

- Bad: it is process-wide, so it would swallow what other threads write meanwhile.

### No validation without a null device

- Good: Saxon's warnings could never reach the standard error.
- Bad: one odd environment would make the command line useless, for warnings that only its
  own user sees; a service is protected by its child process either way.
