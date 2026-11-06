# M3 — `feat/web-repairs`

## Three questions a senior engineer would ask

**1. "Every diff tool shows line numbers. Why doesn't yours?"**

Because they would count the wrong lines. The API does not diff the files as they were sent: it
indents the invoice anew, two spaces a level, before and after the patches, and diffs those
copies. That is deliberate, since a file written on one line would otherwise be one long changed
line, and a changed value is now one changed line whatever the file's layout. But it means the
hunks' numbers are lines of the indented copy. In SRB-001's mutation the report names the type
code on line 16 of the file, and the diff has it on line 7; a reader who opens the file at line 7
finds another element. So `parseDiff()` drops the numbers and keeps a gap where unchanged lines
are left out, and each patch on the page names its canonical path, which is where a reader looks
anyway.

**2. "How do you know the person approves what they read?"**

The page computes nothing. It shows what the API kept when the repair was proposed: what became
of each patch, the diff and the report on the copy. The browser could not compute another diff
if it wanted to, since the API never sends the invoice's content. On approval (the next branch's
button), the API applies the same patches again, only to the document they were proposed for (by
its SHA-256), and only if they leave the document they left then; otherwise it refuses with 409.
So what was read, what is approved and what is stored are the same bytes, or nothing happens.

**3. "The API gives you user ids. How does the page say who proposed a repair?"**

As the visitor would say it: "you" when the id is theirs, "another member" otherwise, "a former
member" when the id is gone with the account (the foreign key is `SET NULL`), and "an API key".
I did not look the names up, because a client's role has no `members:read`: the page would show
names to an owner and ids to a client, two pages to test and explain. Naming members for those
who may read them is a later step, and the wording leaves room for it.

## The one concept to explain unaided

**A diff's numbers count the lines of what was compared.** Here that is the invoice indented
anew, not the file sent, so the page shows the lines without their numbers and lets the
canonical path say where a change is.

## Supporting facts worth remembering

- The page: `/[locale]/invoices/[id]/repairs/[repairId]`; a 404 or a 422 (an id that is not a
  UUID) reads as a repair that does not exist. The history is on the report's page, above the
  layers, asked for once the invoice has been read.
- The keys: `["invoices", "one", id, "repairs"]` and `[..., "repairs", repairId]`, under the
  invoice's, so the approval that changes the invoice will drop them too.
- The diff: `difflib.unified_diff(..., n=2)`; the header ends at the first `@@`, so a removed line
  that starts with `--` is not taken for it; a gap above every hunk but one that starts the
  document. Removed and added lines are `del` and `ins` with hidden "removed:" and "added:".
- The lines scroll sideways in a box that is a named `group` (not a `region`, since the section
  around it is the landmark) with `tabIndex={0}`, so a keyboard can reach and scroll it.
- Found while checking in a browser: Next.js keeps the page just left in the DOM, hidden (React's
  `Activity`), so a CSS locator may find two; and React reveals the streamed language links a
  moment after the page on a route rendered when it is asked for.
