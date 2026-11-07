# M3 — `fix/repair-patches-that-change-nothing`

## Three questions a senior engineer would ask

**1. "How can a patch apply and change nothing, and why does it matter?"**

A replace that writes the value its place already holds: the patch engine applies it, since the
place exists and the operation is allowed, and the document is the same afterwards. Kept, it
made a repair of nothing: a proposal waiting for a person's decision that the page could only
offer to reject, since an approval of it is refused (409, `changes-nothing`). The repairer now
treats it as it treats a failed patch: not kept, and with no other patch to keep, no repair
(422), so the page says that the model proposed nothing a repair could keep.

**2. "Why not refuse such a patch in the patch engine?"**

For the engine it is a correct patch: the place exists, the operation applies, and the document
is still well formed. Whether a patch is worth keeping is the repairer's question, which keeps
patches by what they did. A person's own repair, sent through the API, keeps the patches it was
given, and its outcomes show that one changed nothing.

**3. "What does the model learn from it?"**

In the second round it reads "applied, but it changed nothing: its place held this value
already" instead of "applied", so that it does not take the violation for repaired. If it
proposes the same patch again, it is applied again and dropped again, which costs a validation
and nothing else.

## The one concept to explain unaided

**Judge a step by what it did, not by whether it ran.** An operation that succeeded and changed
nothing is, for a repair, the same as one that failed.

## Supporting facts worth remembering

- The engine's outcome of an applied patch holds `before` and `after`; when they are equal, the
  patch changed nothing.
- A patch a person decides is still kept: it is a suggestion for the person and changes nothing
  by design.
- Found in `feat/web-repair-suggestion`: a stand-in model that wrote the type code 380 into
  every invoice made, of one whose code was 380 already, a repair of nothing.
