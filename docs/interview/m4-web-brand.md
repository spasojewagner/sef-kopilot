# M4 — `feat/web-brand`

## Three questions a senior engineer would ask

**1. "Why measure contrast in a unit test rather than run an accessibility scanner?"**

A scanner such as axe measures a rendered page: the states a test happens to visit, in the
mode the browser happens to be in. The tokens are where the colours are decided, so the test
measures them there, every pair a page sets together, in light, in dark and on the navy, in
milliseconds. A token changed to a failing value fails the commit that changed it. A scanner in
the end-to-end test would still be worth adding for what tokens cannot see: opacity, images,
text over a picture.

**2. "Why not `next/font`, which Next.js recommends?"**

`next/font/google` downloads the fonts while building, a request the self-hosted build should
not need. `next/font/local` declares no character ranges, so each weight would be one file
holding Latin, Latin Extended and Cyrillic, which the packages split by range. The
`@fontsource-variable` CSS keeps the ranges: a page in English loads only Latin. The price is
the fallback with matching metrics that `next/font` computes, which ADR-0043 accepts.

**3. "The header is navy in light mode. How do shadcn/ui's buttons inside it know?"**

They do not need to: they read CSS custom properties (`bg-background`, `border-input`), and
custom properties are inherited. `surface-ink` sets those properties again on the header, so
everything inside it resolves them to the navy's values. No variant, no prop, no context; the
same components, re-themed by the cascade.

## The one concept to explain unaided

**Contrast is a ratio of luminances**, (L1 + 0.05) / (L2 + 0.05), with green weighing ten
times blue; OKLCH puts a perceived lightness in the colour's first number, so a palette built
in it can be made readable by stepping lightness, and checked by arithmetic.

## Supporting facts worth remembering

- AA asks 4.5:1 for text and 3:1 for a focus ring, an icon or a control's edge.
- The brand's teal beside the background is 3.2:1: enough for the mark, not for text; text
  that says "valid" uses a darker teal (`success`, 5.0:1).
- Every page has one `main`, rendered by the root layout: the skip link's target cannot be
  forgotten by a new page.
- The section links read the path only once a member is signed in, which a page rendered at
  build time never knows: reading it there would stop the build of a page whose path is known
  only when it is asked for.
