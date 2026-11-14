# M7 — `fix/web-fresh-verdict-after-approval`

## Three questions a senior engineer would ask

**1. "Stale-while-revalidate is TanStack Query's whole point. Why not show the cached report
while the fresh one loads?"**

Because the cached verdict is not slightly old. It is wrong in the one way the person just
acted on. Stale-while-revalidate suits data that drifts: a list that gained a row, or a
count that moved. It is wrong for data the person's own action has just made false. After an
approval, the cached report says "invalid" about an invoice that is now valid. Showing it, even
for a moment, says the approval failed. So what the approval changed is dropped from the cache,
not marked stale. The invoice is read again before the approval is shown as made, and the page
then has the right verdict, or nothing and its loading state. It never has the wrong one.

**2. "Why not have the approval answer with the new invoice, and save a request?"**

It would save one request, and it would make the decision's endpoint answer for two
resources. The API answers a decision with the repair, which is what was decided. The
invoice has its own route, its own permission check and its own shape, and a second shape
returned elsewhere would drift from it. The cost here is one read, made once, by the person
who approved. The approval is shown a few milliseconds later, which they wait through
anyway.

**3. "Removing queries an observer still watches is a known trap. How do you know none
is watched?"**

On the repair's page, the only query of the invoice that is watched is the decided repair
itself, and the removal leaves it out by its hash. The report, the explanations, the
repairs and the list are shown on other pages. They are removed while nothing watches
them, and read again when a page that shows them mounts. A test pins it: after an
approval, the invoice and its repairs in the cache are the fresh ones, and the explanations
and the list are gone. A second test pins a failed read: it leaves the invoice to be read
when it is shown, never shown as it was.

## The one concept to explain unaided

**A cache invalidated by the user's own action should be replaced, not revalidated.** Showing
old data while new data loads is a good default only while old data is still roughly true. Once
the person has done something that makes it false, the fresh data has to be read first.
