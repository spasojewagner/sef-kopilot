# 43. The web application's look is a set of tested tokens, on the brand's navy

- Status: accepted
- Date: 2026-11-07
- Deciders: the team, at the maintainer's request for a stronger visual identity
- Technical story: branch `feat/web-brand`; the shadcn/ui and dark-mode choices of ADR-0026

## Context and problem statement

The web application wore shadcn/ui's neutral theme: the system's font, black buttons, no mark
and no favicon. Its readers, people who judge ERP and e-invoicing software, met a page that
said nothing of what it was. The product needed a visual identity of its own, one that does not
borrow the colours or emblems of the state's SEF platform it is independent of, and that stays
readable in both modes. How should the look be defined so that every page takes it, and so
that a later change cannot make text unreadable unnoticed?

## Decision drivers

- One place to change the look; the shadcn/ui components unchanged, so that the CLI can still
  update them.
- Readable text by measure, not by eye: WCAG 2.2 AA in light, dark and on the brand's navy.
- Serbian text: č, ć, đ, š, ž, and Cyrillic, in the brand's typeface.
- A self-hosted deployment calls nothing but its model's provider (the brief), and its build
  should need nothing but the package registries.
- An identity of its own, not to be mistaken for the official platform.

## Considered options

1. **Tokens under shadcn/ui's names, in OKLCH, with a navy surface that sets them again for
   what it holds, and a test of their contrast; the typefaces from the `@fontsource-variable`
   packages; the mark drawn in SVG.** Chosen.
2. shadcn/ui's neutral theme with an accent colour added.
3. Variants of each component for the navy surfaces.
4. `next/font` for the typefaces.

## Decision outcome

**Colours** are CSS variables in `src/app/globals.css`, under the names shadcn/ui's
components read: ink navy (`#0B1F33`) for text and the primary action, on a cool off-white
with white cards; every grey tinted towards the navy's hue; one accent, a teal (`--brand`),
which also marks what is valid (`--success`), beside `--warning` and `--destructive`. Dark mode
sets the same names, deeper, under the operating system's preference, as before. The values are
OKLCH, whose lightness is the lightness the eye sees, so that a step in it is a step in
contrast.

**The navy surface is a scope, not a variant.** `surface-ink` sets the tokens again for the
elements inside it: the header, in both modes, and the home page's first screen. A ghost or an
outline button inside it is light on navy with no class of its own.

**Contrast is a test.** `src/app/tokens.test.ts` reads the stylesheet and measures every pair a
page sets together: text on its surface at 4.5:1, the accent and the focus ring beside the
background at 3:1, in light, in dark and on the navy in each. A token changed to a value that
fails is a failing test, before anyone looks at a page.

**Typefaces**: Onest for the text, JetBrains Mono for rule ids, paths, XML and amounts. Their
CSS is imported from the `@fontsource-variable` packages in the root layout, and the build
serves the files with the pages: one variable file for each range of characters, so that a
browser loads Latin, Latin Extended or Cyrillic only when a page has them.

**The mark** is a compass bezel whose needle is a check: the course an invoice keeps through
the rules. It is an SVG of our own, in `src/components/logo.tsx`, where the ring takes the
text's colour and the check the accent. `src/app/icon.svg`, the favicon, draws the same paths in
fixed colours, and a test keeps the two equal. The raster images that cannot be SVG,
`apple-icon.png` and `favicon.ico`, are rendered from the favicon by `pnpm brand:images`
(Chromium, through Playwright) and committed.

### Consequences

Good:

- The components of `src/components/ui` are as the registry wrote them; the brand is a
  stylesheet.
- A colour that would fail the contrast it is used for fails a test, in each mode.
- No request leaves the build for fonts; the typefaces cover Serbian in both scripts.

Bad / accepted:

- The fonts have no `size-adjust` fallback: a slow first load can show the system's font
  before Onest (`font-display: swap`), and move the text a little.
- The test knows the pairs the pages use; a new pairing of tokens must be added to it.
- The raster icons are committed images, to render again when the mark changes.

## Pros and cons of the options

### shadcn/ui's neutral theme with an accent

- Good: the smallest change.
- Bad: the pages would still look like every other shadcn/ui project, which is the problem.

### Variants for the navy surfaces

- Good: each component says explicitly how it looks on navy.
- Bad: a variant per component and per surface, which the CLI's updates would have to keep;
  a scope does it once.

### `next/font`

- Good: preloads the files and computes a fallback with matching metrics.
- Bad: `next/font/google` downloads the fonts while building, a request the self-hosted build
  must not make; `next/font/local` declares no character ranges, so one file per weight would
  have to hold Latin, Latin Extended and Cyrillic, which the packages split.
