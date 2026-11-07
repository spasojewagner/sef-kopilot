# 36. Colour you can read: OKLCH and the contrast ratio

Whether a text can be read on its background is a number, not a matter of taste. WCAG 2 gives
it as a **contrast ratio**, from 1 (the same colour) to 21 (black on white):

```text
contrast = (L1 + 0.05) / (L2 + 0.05)     L1 the lighter colour's relative luminance, L2 the darker's

relative luminance L = 0.2126 R + 0.7152 G + 0.0722 B    R, G, B in linear light (sRGB without its gamma)
```

Green weighs ten times what blue does: the eye is far more sensitive to it. Level AA, the level
public-sector and procurement rules usually ask for, wants **4.5:1** for text and **3:1** for
what must be seen but not read: a focus ring, an icon, the edge of a control (1.4.3, 1.4.11).

**Why the tokens are OKLCH.** In `#0E9F8E` or in HSL, lightness is a property of the numbers,
not of what the eye sees: HSL's yellow and blue at 50 % lightness look nothing alike. OKLCH's
three numbers are a perceived **L**ightness (0 to 1), a **C**hroma (how colourful) and a
**H**ue angle. Two colours with the same L look about as light; lowering L darkens a colour
without shifting its hue. A palette is then a hue (the navy's 250°, the teal's 182°) and a few
lightness steps, and contrast follows lightness:

```text
--foreground  oklch(0.234 0.047 250.5)   ink navy        16.0:1 on the off-white background
--muted-fg    oklch(0.5   0.033 250)     tinted grey      5.7:1  (at L 0.58 it would fail: 4.1)
--brand       oklch(0.631 0.111 181.6)   teal             3.2:1  beside it: enough for a mark,
                                                                 not for text, so text that
--success     oklch(0.48  0.09  183)     a darker teal    5.9:1  says "valid" uses this one
```

A badge sets a state's words on a 12 % tint of the same colour, which the test measures as a
browser draws it: mixed with the surface in sRGB as stored, gamma and all, not in linear light
(half black over white is `#808080`, 3.95:1). At `oklch(0.52 …)` the teal read at 4.3:1 on its
tint over the page, so it is a step deeper.

**The test, not the eye.** `tokens.test.ts` reads `globals.css`, converts each `oklch()` to
linear sRGB (the OKLab matrices), computes the ratio for every pair a page sets together, in
light, in dark and on the navy, and fails below the threshold. A designer can then change any
token freely: a value that hurts the reader fails before review, in the mode where it does.

**What it does not see.** Opacity (`bg-destructive/60`) mixes a token with whatever lies
under it, which only a rendered page knows; a pairing the lists do not name is not measured; and
WCAG 2's formula is known to flatter dark mode a little (its successor drafts a new one,
APCA). The ratio is the floor, not the design.
