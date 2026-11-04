# M2 — `fix/core-hostile-documents`

## Three questions a senior engineer would ask

**1. "Validation was quadratic. How did you find it, and how do you know it is fixed?"**

The security review of the invoice endpoint generated legal invoices of growing size and
timed them. Doubling the lines roughly quadrupled the time: 4000 lines took 11 s and 8000
took 39 s. A profile of one run (cProfile, sorted by own time) put 3.3 s of 5.7 s in
`canonical_xpath`, called 12 000 times. Each call read all of an element's same-named
siblings to find its position, so addressing N lines read N siblings N times.

The fix reads each element's children once per block, in an index scoped to the validation.
Three tests hold it:

- a property test checks that every XPath is unchanged;
- a test counts that each parent's children are read once;
- a test counts what each layer, and the pipeline, reads while it addresses 300 lines, so a
  layer whose entry point loses its block fails.

The curve is linear again: 8000 lines take 5 s.

**2. "A comment made a wrong invoice pass. How?"**

XML lets a comment sit inside a value: a payable amount written `14400<!-- -->1` is 144001
to the schema and to CEN's rules. lxml kept the comment, so the value was two text nodes, and
`element.text`, which our model read, stops at the first: 14400. Our arithmetic layer checks
CEN's calculation rules in their place (their own reports are set aside), so it was the only
reader that mattered, and it saw totals that added up. Two readers of one document that
disagree are a parser differential, the family of HTTP request smuggling. The fix is at the
boundary: the parser drops comments and processing instructions, which mean nothing in UBL,
so there is one reading for everyone, the published rule sets included. A test puts a
comment in the middle of every value of the whole corpus and checks that no verdict changes;
another checks that this amount is reported.

**3. "Why refuse numbers longer than 28 digits instead of raising the decimal precision?"**

`xs:decimal` has no bound, so any fixed precision breaks for a long enough number: a
million-digit amount is schema-valid. The bound sits in the model, where the failure has a
name: a `MODEL` violation pointing at the element. Inside the bound, the checks run in a
128-digit context, which holds sums and products of such numbers exactly. That fixes the
silent bug too: Python's default 28 digits rounded large sums, where CEN computes with
arbitrary precision.

## The one concept to explain unaided

**Accidentally quadratic.** A loop that looks linear calls something that is itself linear in
the same input. Here it was "find my position among my siblings" for every sibling. Find it
with a profiler on a scaled-up input, and confirm it with the curve: doubling N quadruples
the time. Fix it by doing the inner work once and remembering it, with an index.

## Supporting facts worth remembering

- What remains of the cost of a hostile document is inside the published rule sets. It grows
  faster than linearly with failing elements, and the rules cannot be changed. Saxon also
  holds the GIL while it runs, so the API has to bound both.
- The index lives in a context variable, so every thread has its own, and it is gone when
  the outermost block ends.
- Saxon printed warnings that quote the document on file descriptor 2. Redirecting that
  descriptor would swallow other threads' output, and Saxon's own setting only works when the
  processor is made (measured), so the processor is made from a one-line configuration file.
  The test captures the real descriptors: a Python log capture never sees native output.
- Amounts in the Serbian extension now need the form of `xs:decimal`: `1E3` is not one, and
  neither are Arabic-Indic digits, which Python's `\d` and `Decimal` accept.
- A report lists at most `max_violations` set-aside violations too: 8000 empty extension
  elements made a 7.6 MB report before.
- A refused DOCTYPE is checked after parsing, so the parser's own settings are what stop XXE
  while it parses; tests now fail if entity resolution or DTD loading is turned on.
