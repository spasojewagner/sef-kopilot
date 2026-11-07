# M4 — `feat/web-landing`

## Three questions a senior engineer would ask

**1. "Why CSS animations, not a motion library?"**

The page is a server component that sends no JavaScript of its own; one sequence, played once,
needs nothing a stylesheet cannot do. The end of the story is the element's own style, and the
animations run only under `prefers-reduced-motion: no-preference`, so a visitor who asks for
less motion, or a page whose animations do not run, shows all of it. A library would add a
client bundle and hydration for a few keyframes.

**2. "Is the example real, or marketing?"**

It is the golden path's own case: the synthetic invoice whose type code is 393, rule SRB-001 as
the validator states it, the reference the rule names (SRB-CIUS 1.3, Table 1, BT-3) and the
date the corpus gives that edition, 6 June 2025. It is written into the page rather than asked
of the API, because the home page must not call the API or a model to be shown, and the demo's
API sleeps.

**3. "Why does the image of a shared link need `SITE_URL`?"**

Open Graph wants the image's whole address, and a page rendered at build time does not know the
host it will be served from. On Vercel, Next.js reads the project's address from the platform;
anywhere else it would name `http://localhost:3000`. The end-to-end test builds with the test's
address and fetches the image the page names.

## The one concept to explain unaided

**Motion with its end first**: write the element's style as the final state and let the
animation, allowed by the media query, play the way there, so that without motion nothing is
hidden.

## Supporting facts worth remembering

- The navy scope sets tokens and text only; an element paints the navy itself
  (`bg-background`), which is how the first screen leaves room below its edge for the example.
- A CSS module compiles as global CSS here (the Turbopack rule that runs Tailwind on every
  stylesheet), so the story's styles are global, prefixed `story-`.
- A grid's implicit column is as wide as its widest content: a long code line made the phone's
  page wider than the screen until the columns were `minmax(0, 1fr)`.
