# M4 — `feat/web-app-restyle`

## Three questions a senior engineer would ask

**1. "Why tinted badges rather than solid colours?"**

A solid red badge is the loudest thing on a report, louder than the invoice's number. A state
in its own colour on a tint of it says the same and keeps the page's order: the heading first,
the state beside it. The price is contrast: words on a tint of their own colour read worse
than on the card, so the token test measures each state on its tint, in light, in dark and on
the navy, and the light theme's colours are a step deeper to pass.

**2. "Why does the test mix the tint in sRGB, not in linear light?"**

Because that is how a browser draws `bg-success/12`: it blends the stored, gamma-encoded
values, as the compositing specification says. Mixing in linear light would make the tint
darker than the screen shows, and pass colours that fail. The test's own check holds it to the
known case, half black over white, `#808080`, 3.95:1.

**3. "Why move the way back above the page, and keep only one?"**

A way back belongs where a reader looks for where they are, above the heading, as a breadcrumb
does; at the foot of a long report it was found last. Two links with the same name to the same
place would be noise to a screen reader, and the end-to-end test finds its links by name.

## The one concept to explain unaided

**Alpha is mixed on stored values**: a colour at 12 % over a surface is `0.12 × colour +
0.88 × surface` in gamma-encoded sRGB, and only then turned into light to measure contrast.

## Supporting facts worth remembering

- The badges are shadcn/ui variants of our own, `error`, `warning`, `success`: a new state
  takes its look by name.
- The layers' checklist is an ordered list, the marks hidden, the words read; on a wide screen
  it stays beside the rules (`sticky`).
- Signing in reuses the home page's words for its navy panel: no new messages to translate.
