/**
 * Renders the brand's raster images from the mark in `src/app/icon.svg`, in Chromium: the icon
 * a phone puts on its home screen (`apple-icon.png`) and the favicon of browsers that take no
 * SVG (`favicon.ico`). The images are committed and the build does not run this; run it after
 * changing the mark, from `apps/web`:
 *
 *     pnpm brand:images
 */
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";

import { chromium } from "@playwright/test";

const APP = path.join(import.meta.dirname, "../src/app");

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
} finally {
  await browser.close();
}
