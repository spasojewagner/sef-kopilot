/**
 * Renders the brand's raster images from the mark in `src/app/icon.svg`, in Chromium: the icon
 * a phone puts on its home screen (`apple-icon.png`), the favicon of browsers that take no SVG
 * (`favicon.ico`), and the image a shared link shows (`[locale]/opengraph-image.png`), on the
 * home page's backdrop and in the pages' typeface. The images are committed and the build does
 * not run this; run it after changing the mark or the backdrop, from `apps/web`:
 *
 *     pnpm brand:images
 */
import { readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";

import { chromium } from "@playwright/test";

const APP = path.join(import.meta.dirname, "../src/app");
const BACKDROP = path.join(
  import.meta.dirname,
  "../src/components/landing/backdrop.svg",
);
const require = createRequire(import.meta.url);

/** A file as a `data:` URL, so that the page loads nothing from anywhere. */
async function inline(file, type) {
  return `data:${type};base64,${(await readFile(file)).toString("base64")}`;
}

/** The typeface's file for `range` (`latin`, `latin-ext`), as a `data:` URL. */
function onest(range) {
  return inline(
    require.resolve(
      `@fontsource-variable/onest/files/onest-${range}-wght-normal.woff2`,
    ),
    "font/woff2",
  );
}

/** The favicon's sizes: a tab's, a high-density tab's and a shortcut's. */
const FAVICON_SIZES = [16, 32, 48];

/** An ICO file of PNG images, which every current browser and system reads. */
function ico(images) {
  const header = Buffer.alloc(6 + 16 * images.length);
  header.writeUInt16LE(0, 0); // reserved
  header.writeUInt16LE(1, 2); // an icon, not a cursor
  header.writeUInt16LE(images.length, 4);
  let offset = header.length;
  images.forEach(({ size, png }, index) => {
    const entry = 6 + 16 * index;
    header.writeUInt8(size % 256, entry); // width; 0 stands for 256
    header.writeUInt8(size % 256, entry + 1); // height
    header.writeUInt8(0, entry + 2); // no palette
    header.writeUInt8(0, entry + 3); // reserved
    header.writeUInt16LE(1, entry + 4); // colour planes
    header.writeUInt16LE(32, entry + 6); // bits per pixel
    header.writeUInt32LE(png.length, entry + 8);
    header.writeUInt32LE(offset, entry + 12);
    offset += png.length;
  });
  return Buffer.concat([header, ...images.map(({ png }) => png)]);
}

const mark = await readFile(path.join(APP, "icon.svg"), "utf8");
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ deviceScaleFactor: 1 });

  /** `svg` drawn to fill a square of `size` pixels, its transparency kept. */
  async function render(svg, size) {
    await page.setViewportSize({ width: size, height: size });
    await page.setContent(
      `<!doctype html><style>*{margin:0}svg{display:block;width:${size}px;height:${size}px}</style>${svg}`,
    );
    return page.screenshot({ type: "png", omitBackground: true });
  }

  // A phone rounds the icon's corners itself, and asks for a square with no transparency.
  const square = mark.replace(/ rx="[\d.]+"/, "");
  await writeFile(path.join(APP, "apple-icon.png"), await render(square, 180));

  const images = [];
  for (const size of FAVICON_SIZES) {
    images.push({ size, png: await render(mark, size) });
  }
  await writeFile(path.join(APP, "favicon.ico"), ico(images));

  // The mark on the navy, its ring light, without the favicon's tile.
  const light = mark
    .replace(/<rect [^>]*\/>/, "")
    .replace('viewBox="0 0 64 64"', 'viewBox="8 8 48 48"');
  await page.setViewportSize({ width: 1200, height: 630 });
  await page.setContent(`<!doctype html>
<style>
  @font-face { font-family: Onest; font-weight: 100 900; src: url(${await onest("latin")}) format("woff2"); }
  @font-face { font-family: Onest; font-weight: 100 900; src: url(${await onest("latin-ext")}) format("woff2");
    unicode-range: U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, U+02DD-02FF; }
  * { margin: 0; }
  body { width: 1200px; height: 630px; background: #0b1f33 url(${await inline(BACKDROP, "image/svg+xml")}) center / cover;
    font-family: Onest; color: #e6edf3; display: grid; align-content: center; padding: 0 96px; box-sizing: border-box; }
  h1 { display: flex; align-items: center; gap: 28px; font-size: 84px; font-weight: 600; letter-spacing: -0.03em; }
  svg { width: 104px; height: 104px; }
  p { margin-top: 36px; font-size: 32px; color: #8ea0b4; letter-spacing: -0.005em; }
</style>
<h1>${light}SEF Kopilot</h1>
<p>UBL 2.1, EN 16931, SRB-CIUS, Peppol BIS Billing 3.0</p>`);
  await page.evaluate(() => document.fonts.ready);
  await writeFile(
    path.join(APP, "[locale]", "opengraph-image.png"),
    await page.screenshot({ type: "png" }),
  );
} finally {
  await browser.close();
}
