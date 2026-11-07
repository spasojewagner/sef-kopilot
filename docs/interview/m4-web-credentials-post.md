# M4 — `fix/web-credentials-post`

## Three questions a senior engineer would ask

**1. "Why not just add `method="post"` and be done?"**

That keeps the password out of the address, but the form would still be sent before the page's
script, and the server would answer with the page: the person sees nothing happen. The button
waiting for the script stops the early send, and with it the Enter key, since a disabled default
button blocks a form's implicit submission. The POST is the second wall, for a form sent anyway.

**2. "How does a component know that the page's script has taken over?"**

`useSyncExternalStore` with a server snapshot of `false` and a client snapshot of `true`. React
uses the server snapshot while it hydrates, so the markup matches what the server sent, then
renders again with `true`. No effect and no state: nothing to clean up, and no warning of a
mismatch.

**3. "How do you test what the server sends, in a test that runs in a browser-like DOM?"**

`renderToString` of the form with its providers, its markup put into an element of the test's
document: the form says `method="post"` and its button is disabled. The tests that render it in
the browser then press the same button, so both halves are held.

## The one concept to explain unaided

**Hydration**: a page built ahead of time is interactive before React attaches its handlers.
Anything that must happen only through the script, a form that calls an API, has to be inert in
the markup the server sends.

## Supporting facts worth remembering

- Found in a preview whose server still held an older build: its script never loaded, and a
  registration went out as a GET with the password in the address.
- A POST to a page built ahead of time is answered with the page (checked against `next start`);
  nothing echoes the password.
- The consent page's sign-in is the same form, and is held the same way.
