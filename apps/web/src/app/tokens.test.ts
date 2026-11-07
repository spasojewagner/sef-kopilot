// @vitest-environment node
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const STYLESHEET = readFileSync(
  new URL("./globals.css", import.meta.url),
  "utf8",
);

type Tokens = Record<string, string>;

/** The custom properties set by the block that opens with `opening`, by name. */
function tokensOf(opening: string): Tokens {
  const start = STYLESHEET.indexOf(opening);
  expect(start, `globals.css has no block ${opening}`).toBeGreaterThan(-1);
  const body = STYLESHEET.slice(start, STYLESHEET.indexOf("}", start));
  return Object.fromEntries(
    [...body.matchAll(/--([\w-]+):\s*([^;]+);/g)].map((match) => [
      match[1],
      match[2].trim(),
    ]),
  );
}

const LIGHT = tokensOf(":root,\n.surface-page {");
const DARK = tokensOf(
  "@media (prefers-color-scheme: dark) {\n  :root,\n  .surface-page {",
);
/** The navy surface sets only what it changes; the rest comes from the page around it. */
const INK = (page: Tokens): Tokens => ({
  ...page,
  ...tokensOf("@utility surface-ink {"),
});

/** An opaque `oklch(L C H)` colour as linear sRGB, clipped to the gamut. */
function linear(colour: string): [number, number, number] {
  const match = /^oklch\(([\d.]+) ([\d.]+) ([\d.]+)\)$/.exec(colour);
  expect(match, `${colour} is not an opaque oklch() colour`).not.toBeNull();
  const [lightness, chroma, hue] = match!.slice(1).map(Number);
  const a = chroma * Math.cos((hue * Math.PI) / 180);
  const b = chroma * Math.sin((hue * Math.PI) / 180);
  const l = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (lightness - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const clip = (value: number) => Math.min(1, Math.max(0, value));
  return [
    clip(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
    clip(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
    clip(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s),
  ];
}

/** WCAG 2's contrast ratio of two colours, from 1 to 21. */
function contrast(first: string, second: string): number {
  const luminance = (colour: string) => {
    const [r, g, b] = linear(colour);
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const [high, low] = [luminance(first), luminance(second)].sort(
    (x, y) => y - x,
  );
  return (high + 0.05) / (low + 0.05);
}

/** Text the pages set on a surface: WCAG 2.2's 4.5:1 for normal text (1.4.3, level AA). */
const TEXT: [string, string][] = [
  ["foreground", "background"],
  ["card-foreground", "card"],
  ["popover-foreground", "popover"],
  ["primary-foreground", "primary"],
  ["secondary-foreground", "secondary"],
  ["accent-foreground", "accent"],
  ["muted-foreground", "background"],
  ["muted-foreground", "card"],
  ["muted-foreground", "muted"],
  ["brand-foreground", "brand"],
  ["success", "background"],
  ["success", "card"],
  ["warning", "background"],
  ["warning", "card"],
  ["destructive", "background"],
  ["destructive", "card"],
];

/** What must be seen beside the background, not read: 3:1 (1.4.11, non-text contrast). */
const GRAPHICS: [string, string][] = [
  ["ring", "background"],
  ["brand", "background"],
  ["brand", "card"],
];

describe.each([
  ["light", LIGHT],
  ["dark", DARK],
  ["the navy surface, in light", INK(LIGHT)],
  ["the navy surface, in dark", INK(DARK)],
])("The design tokens, %s", (_, tokens) => {
  it.each(TEXT)("set %s on %s at 4.5:1 or more", (text, surface) => {
    expect(contrast(tokens[text], tokens[surface])).toBeGreaterThanOrEqual(4.5);
  });

  it.each(GRAPHICS)("set %s beside %s at 3:1 or more", (mark, surface) => {
    expect(contrast(tokens[mark], tokens[surface])).toBeGreaterThanOrEqual(3);
  });
});

describe("Contrast", () => {
  it("is measured as WCAG measures it", () => {
    expect(contrast("oklch(1 0 0)", "oklch(0 0 0)")).toBeCloseTo(21, 5);
    expect(contrast("oklch(0.5 0 0)", "oklch(0.5 0 0)")).toBe(1);
    // #767676, the darkest grey that still passes on white, at 4.54:1.
    expect(contrast("oklch(0.5658 0 0)", "oklch(1 0 0)")).toBeCloseTo(4.54, 1);
  });
});
