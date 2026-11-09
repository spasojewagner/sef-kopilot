# M5 — `feat/web-sef-key`

## Three questions a senior engineer would ask

**1. "The browser holds the SEF key for a moment. How long, and where?"**

Only in the field's state while the owner types it, and in the one request that sends it. The
field is a password input with autocomplete off, so the browser neither shows it nor offers to
remember it; once the API answers that it is saved, the field is emptied. The key never enters
the query cache: what the page learns from the answer is the time it was set, which it writes
into the cached organization. Nothing on the page can read the key back, because the API never
returns it.

**2. "Why check the key in the browser when the API checks it anyway?"**

To say at once what is wrong, and to send nothing that cannot be a key: the API answers a 422
that never repeats what it refused, so the page names the rule (8 to 200 visible characters,
no spaces) before the request, and the same rule after it if the API disagrees. The API's check
stays the one that decides.

**3. "Removing the key is one button. Why ask twice?"**

Because without a key nothing is sent to SEF for the organization, and the page cannot undo it
without the key itself, which the owner may no longer have at hand. The second press says so,
and says that SEF's own key stays valid until it is revoked in SEF, which is the step that
actually takes the power away from a leaked key.

## The one concept to explain unaided

**A write-only secret in a user interface**: the page sends it once, keeps none of it after
the answer, and shows only facts about it (since when it is set), never the secret.

## Supporting facts worth remembering

- The page was the first to send PUT, which the API's CORS answer did not allow: the browser
  refused it before the API saw it. Unit tests that stub the API cannot see a preflight; a test
  now compares every method in the OpenAPI document with those a page may send.

- The focus follows the confirmation and comes back to the button when it is cancelled, as on
  the retention card.
- An uncertain failure has the organization read again; a 403 has the role read again.
