# M3 — `fix/web-header-phone`

## Three questions a senior engineer would ask

**1. "Why move the languages to the footer instead of making everything smaller?"**

Because I measured, and smaller did not fit. At 360 px the header has 312 px inside its padding;
the name takes 83 and its gap 16, and the right side needed 306 px in Serbian and 319 in English.
Language codes ("SR", "EN") would save about 60 px, which is not enough for English at 360, and
tighter padding and gaps would fit one font at one width and break at the next. Below 640 px the
languages now sit in the footer, which has room, and the header keeps the name on one line and
the account, down to 320 px in both languages. Above 640 px the account's address, which is
truncated already, is what gives way.

**2. "Why an invisible copy of the links while they load? Why not nothing, or a skeleton?"**

The links need the page's path, which a page rendered when it is asked for knows only then;
React streams them, and reveals streamed boundaries together after a short wait, so they arrive
a moment after the rest. With nothing in their place they push whatever follows them, and in
the footer that is the notice and the API's status: a layout shift. A skeleton would keep the
space but draw the eye to something that is about to change. The same names in the same button
boxes have exactly the links' size in either language, are invisible, hidden from screen readers
and not links, so nothing moves and there is nothing to click by mistake.

**3. "jsdom has no layout. How did you check a layout fix?"**

In Chromium, with Playwright, at 320, 360, 390, 640, 700 and 1024 px, signed in, in both
languages: the page's `scrollWidth` against its `clientWidth`, the number of lines of the name,
whether the header or the footer shows the links, and the `layout-shift` entries of a
`PerformanceObserver` whose sources are in the header. Before, the page scrolled sideways by up
to 51 px; after, it never does, and nothing in the header shifts on a phone. On wider screens a
shift of 0.01 to 0.016 remains: the account appears once the session is known, by design, so
that a signed-in visitor never sees "Prijava" flash by. The unit tests pin what jsdom can see:
the kept place while the path is not known, and which screens show the languages where.

## The one concept to explain unaided

**Keep the place of what comes later.** Whatever a page shows after its first paint, streamed or
fetched, takes the size it will have from the start, so that nothing around it moves.

## Supporting facts worth remembering

- Tailwind's `sm` is 640 px: `hidden sm:block` in the header, `sm:hidden` in the footer.
- `invisible` is `visibility: hidden`: the box keeps its size, and the browser removes it from
  the accessibility tree; `aria-hidden` says so explicitly.
- The name has `shrink-0` and `whitespace-nowrap`, and the right side `min-w-0`, so that the
  truncated address shrinks first.
- A layout shift is scored by how much of the viewport moved and how far; below 0.1 for a page is
  "good" in Core Web Vitals.
