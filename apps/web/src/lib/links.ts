/** Where the pages link to outside the application. */

/** The project's repository on GitHub. */
export const REPOSITORY_URL = "https://github.com/spasojewagner/sef-kopilot";

/** The repository's synthetic invoices, of made-up companies: the ones for the public demo. */
export const SYNTHETIC_INVOICES_URL = `${REPOSITORY_URL}/tree/main/fixtures/invoices/synthetic`;

/**
 * The address the site is served at, from `SITE_URL`, which a shared link's image needs whole.
 * On Vercel, Next.js knows it without; elsewhere it would take `http://localhost:3000`.
 */
export function siteUrl(): URL | undefined {
  const url = process.env.SITE_URL;
  return url ? new URL(url) : undefined;
}
