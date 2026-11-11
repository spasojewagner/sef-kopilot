import { mkdir, rm, writeFile } from "node:fs/promises";
import path from "node:path";

import {
  expect,
  test,
  type CDPSession,
  type Locator,
  type Page,
} from "@playwright/test";

/**
 * The README's demo (`docs/demo/golden-path.gif`): the end-to-end test's golden path, walked at
 * a person's pace and recorded. A person uploads an invoice whose type code SEF does not accept,
 * reads its report, has the language model suggest a repair, reads its diff, approves it, and
 * finds the invoice valid. The API is the end-to-end test's, so the repair comes from its
 * scripted model (`scripts/serve_e2e_api.py`), and the page says so.
 *
 * Chromium sends the frames itself, lossless and only when the page changes (the DevTools
 * protocol's screencast): what does not move is the same in every frame, which keeps the GIF
 * small. They are written to `test-results/demo/`, with the list of how long each is shown from
 * which `make demo-gif` makes the GIF.
 */

/** The invoice: its type code, 393, is not one SEF accepts (SRB-001). */
const INVOICE = path.join(
  __dirname,
  "../../../fixtures/invoices/synthetic/mutations/srb-001-invoice-type-code.xml",
);
const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
/** Where the frames and their list are written. */
const FRAMES = path.join(__dirname, "../test-results/demo");
/** The page is drawn at 1280 by 720, and its frames scaled down to the GIF's width. */
const PAGE = { width: 1280, height: 720 };
const WIDTH = 960;
/** How long the last frame is shown before the GIF starts again, in seconds. */
const LAST_FRAME_SECONDS = 3;

/**
 * A pointer drawn on the page, since a screencast shows none: it follows the mouse, and shrinks
 * while a button is pressed. Run in the page, before its own scripts.
 */
function drawPointer() {
  const ID = "demo-pointer";
  const place = (pointer: HTMLElement) => {
    pointer.style.left = `${sessionStorage.getItem("demo-x") ?? -40}px`;
    pointer.style.top = `${sessionStorage.getItem("demo-y") ?? -40}px`;
  };
  const install = () => {
    if (document.getElementById(ID) !== null) {
      return;
    }
    const pointer = document.createElement("div");
    pointer.id = ID;
    pointer.style.cssText =
      "position:fixed;z-index:2147483647;pointer-events:none;transform:translate(-3px,-2px)";
    pointer.innerHTML =
      '<svg width="22" height="22" viewBox="0 0 22 22"><path d="M3 2 L3 18 L7.5 13.8 ' +
      'L10.6 20.5 L13.4 19.2 L10.4 12.7 L16.5 12.4 Z" fill="#111" stroke="#fff" ' +
      'stroke-width="1.6" stroke-linejoin="round"/></svg>';
    place(pointer);
    document.documentElement.appendChild(pointer);
  };
  const pressed = (scale: string) => () => {
    const pointer = document.getElementById(ID);
    if (pointer !== null) {
      pointer.style.transform = `translate(-3px,-2px) scale(${scale})`;
    }
  };
  document.addEventListener(
    "mousemove",
    (event) => {
      sessionStorage.setItem("demo-x", String(event.clientX));
      sessionStorage.setItem("demo-y", String(event.clientY));
      const pointer = document.getElementById(ID);
      if (pointer !== null) {
        place(pointer);
      }
    },
    true,
  );
  document.addEventListener("mousedown", pressed("0.82"), true);
  document.addEventListener("mouseup", pressed("1"), true);
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", install);
  } else {
    install();
  }
}

/** The screencast's frames, each with the time Chromium drew it, in seconds. */
type Frame = { png: Buffer; at: number };

async function startScreencast(page: Page): Promise<{
  session: CDPSession;
  frames: Frame[];
}> {
  const session = await page.context().newCDPSession(page);
  const frames: Frame[] = [];
  session.on("Page.screencastFrame", (frame) => {
    frames.push({
      png: Buffer.from(frame.data, "base64"),
      at: frame.metadata.timestamp ?? Date.now() / 1000,
    });
    // Chromium sends the next frame once this one is acknowledged.
    session
      .send("Page.screencastFrameAck", { sessionId: frame.sessionId })
      .catch(() => {});
  });
  await session.send("Page.startScreencast", {
    format: "png",
    maxWidth: WIDTH,
    maxHeight: WIDTH,
    everyNthFrame: 1,
  });
  return { session, frames };
}

/** The frames, and the list `ffmpeg -f concat` reads, with how long each is shown. */
async function writeFrames(frames: Frame[]) {
  await rm(FRAMES, { recursive: true, force: true });
  await mkdir(FRAMES, { recursive: true });
  const list = ["ffconcat version 1.0"];
  for (const [index, frame] of frames.entries()) {
    const name = `${String(index).padStart(5, "0")}.png`;
    await writeFile(path.join(FRAMES, name), frame.png);
    const next = frames[index + 1]?.at ?? frame.at + LAST_FRAME_SECONDS;
    list.push(`file ${name}`, `duration ${(next - frame.at).toFixed(3)}`);
  }
  // The concat demuxer takes the last duration only from a file named after it.
  list.push(`file ${String(frames.length - 1).padStart(5, "0")}.png`);
  await writeFile(path.join(FRAMES, "frames.txt"), `${list.join("\n")}\n`);
}

/** The pointer glides to `target`, as a hand moves a mouse, and rests on it. */
async function pointAt(page: Page, target: Locator) {
  await target.scrollIntoViewIfNeeded();
  const box = await target.boundingBox();
  if (box === null) {
    throw new Error("the demo points at something not on the page");
  }
  await page.mouse.move(
    box.x + Math.min(box.width / 2, 60),
    box.y + box.height / 2,
    { steps: 20 },
  );
  await page.waitForTimeout(350);
}

async function press(page: Page, target: Locator) {
  await pointAt(page, target);
  await target.click();
}

test("the golden path, as the README shows it", async ({
  browser,
  baseURL,
}) => {
  test.setTimeout(180_000);

  // The account is made beforehand, in a context of its own: the demo does not show it.
  const signingUp = await browser.newContext({ baseURL });
  const form = await signingUp.newPage();
  await form.goto("/en/register");
  await form.getByLabel("E-mail address").fill("marija@primer.example");
  await form.getByLabel("Password").fill("a long passphrase for the demo");
  await form.getByLabel("Organization name").fill("Primer d.o.o.");
  await form.getByRole("button", { name: "Create the account" }).click();
  await expect(form).toHaveURL("/en");
  const storageState = await signingUp.storageState();
  await signingUp.close();

  // Less motion keeps the home page's example still, and the GIF small.
  const context = await browser.newContext({
    baseURL,
    storageState,
    viewport: PAGE,
    reducedMotion: "reduce",
  });
  await context.addInitScript(drawPointer);
  const page = await context.newPage();
  await page.goto("/en");
  await page.evaluate(() => document.fonts.ready);
  await page.mouse.move(PAGE.width / 2, PAGE.height / 2);
  const { session, frames } = await startScreencast(page);
  await page.waitForTimeout(2600);

  // An invoice SEF would reject, uploaded.
  await press(
    page,
    page.getByRole("link", { name: "Check an invoice" }).first(),
  );
  await expect(page).toHaveURL("/en/invoices");
  const file = page.getByLabel("Invoice (XML, PDF or picture)");
  await pointAt(page, file);
  await file.setInputFiles(INVOICE);
  await page.waitForTimeout(900);
  await press(page, page.getByRole("button", { name: "Check and keep" }));

  // Its report: the rule it breaks, where, and which layer found it.
  await expect(page).toHaveURL(new RegExp(`/en/invoices/${UUID}$`));
  const rule = page.getByRole("heading", { level: 3, name: "SRB-001" });
  await expect(rule).toBeVisible();
  await page.waitForTimeout(1800);
  await pointAt(page, rule);
  await page.waitForTimeout(600);
  await page.evaluate(() => window.scrollBy(0, 260));
  await page.waitForTimeout(1600);

  // A repair, suggested by the model and checked by the validator on a copy.
  await press(page, page.getByRole("button", { name: "Suggest a repair" }));
  await expect(page).toHaveURL(new RegExp(`/repairs/${UUID}$`));
  await expect(
    page.getByRole("group", { name: "Difference in the invoice" }),
  ).toBeVisible();
  await page.waitForTimeout(2600);
  await page.evaluate(() => window.scrollBy(0, 300));
  await page.waitForTimeout(1800);

  // Approved by a person, with a second press.
  const repair = page.getByRole("article");
  await press(
    page,
    repair.getByRole("button", { name: "Approve", exact: true }),
  );
  await page.waitForTimeout(500);
  await press(page, repair.getByRole("button", { name: "Yes, approve" }));
  await expect(repair.getByRole("status")).toHaveText(
    "The repair is approved: the invoice is now the copy with these changes.",
  );
  await page.waitForTimeout(1800);

  // The invoice, valid.
  await press(page, page.getByRole("link", { name: "Back to the report" }));
  await expect(page).toHaveURL(new RegExp(`/en/invoices/${UUID}$`));
  await expect(
    page
      .getByRole("article")
      .locator("header")
      .getByText("Valid", { exact: true }),
  ).toBeVisible();
  await page.waitForTimeout(600);

  await session.send("Page.stopScreencast");
  await context.close();
  expect(frames.length).toBeGreaterThan(0);
  await writeFrames(frames);
});
