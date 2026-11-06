# 30. A repair's page: the API's diff and report, read as it keeps them

- Status: accepted
- Date: 2026-11-07
- Deciders: Marko Spasojević
- Technical story: milestone M3, branch `feat/web-repairs`; the repairs of ADR-0024 and
  ADR-0025 on the pages of ADR-0028

## Context and problem statement

The API keeps every repair proposed for a stored invoice, by a member, an API key or the
language model (ADR-0024, ADR-0025). For each patch it keeps what became of it: applied, kept
for a person's decision by the guard, or not applied. It also keeps the difference the patches
make and the validator's report on the copy they leave. The invoice does not change until a
person approves the repair, and no page showed one. Where does a person read a repair, and how
is its difference shown?

The browser has neither document. The API sends a stored invoice's report, never its content,
and a repair carries a unified diff that the API wrote when the repair was proposed
(`difflib.unified_diff`, two lines of context). That diff does not compare the files as they
were sent. It compares the invoice indented anew, two spaces a level, so that a changed value
is one changed line whatever the file's own layout. Its line numbers are therefore not those of
the file, nor those its report names: the type code that SRB-001's mutation reports on line 16
is line 7 of its diff.

## Decision drivers

- What a person approves is what they read: the patches, what became of each, and the
  difference the API applies again on approval (ADR-0024).
- No more of the invoice through the browser than the API already sends.
- Nothing on the page that sends a reader to the wrong place.
- A change marked as such, not by colour alone; usable with a keyboard and on a phone.
- No dependency for showing a few lines.
- Room for the next branches: asking the model for a repair, and approving or rejecting one.

## Considered options

Where a repair is read:

1. **Its own page, `/[locale]/invoices/[id]/repairs/[repairId]`, linked from a history on the
   report's page.** Chosen.
2. Expanded in place, on the report's page.

How its difference is shown:

1. **The API's diff, read into lines by `parseDiff()` and shown without its numbers.** Chosen.
2. The same diff with its hunks' numbers.
3. A diff library (diff2html, react-diff-viewer).
4. A diff computed in the browser from the documents before and after.

## Decision outcome

**The page** opens with the moment the repair was proposed and where it stands, then two
facts: who proposed it, with the model when it wrote the patches, and who decided on it and
when, or when another repair's approval superseded it. Each patch follows with what became of
it, its operation and canonical path, the value before and after when it applied, the value it
proposes when the guard keeps it for a person, its reason, and the validator's problem, which is
English and marked `lang="en"`. The diff comes next, and then the report on the copy: its
verdict, a card for each rule it fails and the validator's layers, as the report's page shows
them (the components are shared). A repair the API does not find, or an id it refuses (404,
422), is a repair that does not exist, with the way back to the report.

**The history** sits on the report's page, above the layers: the invoice's repairs, the latest
first, each with the moment it was proposed (the link to its page), who proposed it, where it
stands, the verdict on the copy it leaves, and how many of its patches applied, wait for a
person or could not apply. It is asked for once the invoice has been read.

**Who** is said as the visitor would say it. The API names people by their ids. The page says
"you" for the visitor, "another member" for anyone else, "a former member" where the id is gone
with the account, and "an API key". It does not look the names up: a client may not read the
organization's members (`members:read`), and the page would then read differently by role.

**The keys** are under the invoice's: `["invoices", "one", id, "repairs"]` for the list and
`[..., "repairs", repairId]` for a repair. Whatever changes the invoice, an approval among them,
drops its repairs too.

**The diff** is read by `parseDiff()` into kept, removed and added lines, and a gap where
unchanged lines are left out: above every hunk but one that starts the document. The header and
the hunks' numbers are dropped. Each line is an item of a list; a removed or added line is a
`del` or `ins` element with a visible minus or plus and a visually hidden "removed:" or "added:",
so the change does not rest on colour. A line keeps its width, as XML is written, and the lines
scroll sideways in a box that is a named group the keyboard can focus. The text is shown as
text, which React escapes; no HTML from the diff is rendered.

### Consequences

Good:

- The page shows what the API keeps and will apply again on approval: nothing recomputed, and
  no document downloaded.
- No dependency: some forty lines of parser, with their tests, and no injected HTML.
- Each repair has an address. The approval's buttons of `feat/web-diff-approve` have their
  place on its page, and the model's suggestion of `feat/web-repair-suggestion` can open the
  page of the repair it creates.

Bad / accepted:

- No line numbers. A reader finds a change by its canonical path, shown with each patch, and by
  the lines around it.
- A file written on one line shows indented lines, unlike its own. They are the same XML.
- A request more, after the invoice's, for the history: a missing invoice asks for no repairs.
- Members are not named.

## Pros and cons of the options

### Expanded in place

- Good: no page to open.
- Bad: two reports on one page, the invoice's and the copy's, which look alike and would be
  confused; a long page; no address for one repair, which the approval and the model's
  suggestion need.

### The hunks' numbers

- Good: the look every diff has, and a line to name.
- Bad: they are lines of the indented copy. A reader who opens the file, or reads the report,
  at that line finds another element.

### A diff library

- Good: side-by-side views, changes within a line.
- Bad: a dependency for a few lines. diff2html writes HTML that the page would have to inject,
  which `react/no-danger` forbids; react-diff-viewer computes its own diff from two texts, which
  the browser does not have. Neither knows that the numbers are not the file's.

### A diff computed in the browser

- Good: any view of it.
- Bad: it needs both documents, which the API does not send, and it could differ from what the
  API applies on approval.
