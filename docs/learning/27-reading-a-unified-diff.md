# 27. Reading a unified diff, and what its numbers count

A repair's page shows the difference its patches make to the invoice. The API writes that
difference once, when the repair is proposed, as a *unified diff*: the format of `git diff` and
`diff -u`, which Python's `difflib.unified_diff` writes too. The page reads it; it never computes
one.

```text
--- before                                   the header: the two texts compared
+++ after
@@ -5,5 +5,5 @@                              a hunk: 5 lines from line 5, and 5 from line 5
   <cbc:IssueDate>2026-10-05</cbc:IssueDate>   " " a line both texts have (context)
   <cbc:DueDate>2026-10-20</cbc:DueDate>
-  <cbc:InvoiceTypeCode>393</cbc:InvoiceTypeCode>   "-" only before
+  <cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>   "+" only after
   <cbc:Note>Rok za plaćanje je 15 dana od datuma prometa.</cbc:Note>
   <cbc:DocumentCurrencyCode>RSD</cbc:DocumentCurrencyCode>
```

**A hunk is a change and the lines around it.** `@@ -5,5 +5,5 @@` says that the hunk covers
five lines of the old text from line 5, and five of the new from line 5. Each line after it
starts with one character: a space for a line both texts have, `-` for one only the old has,
`+` for one only the new has. The API asks for two lines of context (`n=2`). Two changes closer
than twice that share a hunk; farther apart, they make two, and the lines between them are left
out. A diff of identical texts is empty.

**The header is not a change.** `--- before` and `+++ after` start with the same characters as
removed and added lines. A parser that looks at the first character alone would read
`--- before` as a removed line, and would read a removed line whose text starts with `--` as a
header. The header ends at the first `@@`; after it, every `-` is a removed line.

**The numbers count the lines of what was compared.** Here that is not the file sent. The API
compares the invoice indented anew, two spaces a level, before and after the patches:

```python
etree.indent(copy, space="  ")
lines = etree.tostring(copy, encoding="unicode").splitlines(keepends=True)
difflib.unified_diff(before, after, "before", "after", n=2)
```

Two reasons. A file written on one line would otherwise be one long changed line, whatever a
patch changed. And the indentation is the same whoever wrote the file, so a change of one value
is a change of one line. The price is that line 7 of the diff is not line 7 of the file. In
SRB-001's mutation, the report finds the type code on line 16 of the file sent, and the diff
shows it on line 7.

**So the page drops the numbers.** `parseDiff()` keeps the kept, removed and added lines, and
puts a gap above each hunk but one that starts the document, where unchanged lines are left out.
A reader finds the place by the canonical path each patch names, and by the lines around it.
Showing numbers that count another text's lines would send them to the wrong element.

**A changed line is marked twice.** Colour alone tells nothing to a reader who cannot see it,
and the diff's `-` and `+` are hidden from screen readers as noise. Each removed or added line
is a `del` or `ins` element, with a visible minus or plus and a visually hidden "removed:" or
"added:". Its text is shown as text: nothing in a diff is ever rendered as HTML.

The question to ask of any numbers on a page: what do they count, and is it what the reader
will look in?
