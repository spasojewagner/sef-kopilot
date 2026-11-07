# 28. A request that creates: a mutation, and what the cache learns from its answer

The report's page asks for two things that cost the language model's requests: the rules'
explanations (note 26) and a repair. They look alike, a button and a POST, but they are not the
same kind of request, and TanStack Query has a tool for each.

**An explanation is a read; a suggestion creates.** Explaining a stored report writes nothing on
the server: asking twice gives the same explanations, so the page keeps them under a key and
shows them again. A suggestion creates a repair, kept by the API until a person decides; asking
twice creates two. A query is the wrong tool for that, because a query runs whenever its
key is wanted and stale: when a component mounts, when the window regains focus, after a
failure. A mutation runs only when the code calls it.

```ts
const suggesting = useMutation({
  mutationFn: () => suggestRepair(invoiceId, language), // POST .../repairs/suggestion
  onSuccess: (repair) => {
    client.setQueryData(repairQuery(invoiceId, repair.id).queryKey, repair);
    void client.invalidateQueries({ queryKey: repairsQuery(invoiceId).queryKey });
  },
});
suggesting.mutate(undefined, {
  onSuccess: (repair) => router.push(`/invoices/${invoiceId}/repairs/${repair.id}`),
});
```

**The answer teaches the cache.** The API answers the POST with the repair it kept, the same
body that `GET .../repairs/{repair_id}` returns. Put under that query's key, it lets the
repair's page open at once, with nothing to ask. What the answer does not carry is the list:
the invoice's repairs now have one more, so the list's key is *invalidated*, marked stale, and
asked for again when a page shows it. Writing the answer in and marking what it changed stale
is the whole of keeping a cache honest after a write.

**Two places for `onSuccess`, two lifetimes.** The hook's `onSuccess` runs whenever the request
succeeds, even if the visitor has left the page meanwhile: the cache should learn of the repair
either way. The one given to `mutate()` runs only while the component that called it is still
mounted. Navigation belongs there: a visitor who went to the list while the model worked stays
on the list.

**A failure waits for the visitor.** A mutation does not retry by itself; this page never asks
again unless the visitor presses the button, and offers it only where asking again could help.
The API's 409s name their reason for that (ADR-0031):

```text
409 nothing-to-repair   the invoice is valid          no offer to try again
409 too-many-waiting    repairs wait for a decision   decide on them first
409 invoice-changed     it changed meanwhile          try again
503, no Retry-After     no model, or no validator     no offer to try again
```

The question to ask of any request a page makes: if it ran twice, what would there be twice?
If the answer is "nothing", it is a query; otherwise it is a mutation.
