# M4 — `feat/web-api-keys`

## Three questions a senior engineer would ask

**1. "The key is shown on the page. How is that safe?"**

It is shown once, the answer of the request that issued it, and never stored by the page: it
lives in the component's state until the member presses "I have kept it", and a reload loses
it, as the API intends (only its digest is kept). Focus moves to it, so a screen reader reads
it at once, and a copy button saves retyping 48 characters. The list shows only the first
characters, by which keys are told apart.

**2. "Why offer only the permissions the role grants, when the API checks anyway?"**

Because a form should not offer a choice that can only fail: a client's role does not reach
every invoice of the organization, so the page does not offer it. The API still refuses what
the role does not grant (403), and the page says so in the member's words; the role may have
changed since the page learned it.

**3. "Why ask twice before revoking?"**

Revoking is immediate and cannot be undone: the machine that uses the key loses access at
once, and a new key must be configured on it. The second press says that, in the key's name;
cancelling sends nothing. The list is read again whatever the answer, so it shows the keys
that work.

## The one concept to explain unaided

**Show-once secrets**: a credential the server keeps only as a digest can be shown exactly
once, at issue; the interface's job is to make that one moment hard to miss and easy to use.

## Supporting facts worth remembering

- "Works until" is a day; the key works through it, in the member's time, and stops at the
  start of the next.
- The screenshots were taken against a local throwaway database, with a key issued and used
  for real.
