import type { Schemas } from "@/lib/api";
import { authorized } from "@/lib/session";

/**
 * The organization's credits, where the server's billing is on (ADR-0059): what it holds, what
 * an invoice costs, the packs on sale where the server sells them (ADR-0060), and the ledger.
 */
export type Billing = Schemas["Billing"];

/** A change of the organization's credits, as the ledger has it. */
export type CreditEntry = Schemas["CreditEntryOut"];

/** A pack of credits on sale, its price in cents of its currency. */
export type CreditPack = Schemas["PackOut"];

/** How many of the latest entries of the ledger the page shows. */
export const ENTRIES_SHOWN = 20;

/** Whether storing an invoice costs a credit here, and how many the organization holds. */
export function getBilling(signal?: AbortSignal): Promise<Billing> {
  return authorized<Billing>("/billing", { signal });
}

/** The latest changes of the organization's credits, newest first; only an owner may. */
export function listCreditEntries(
  signal?: AbortSignal,
): Promise<CreditEntry[]> {
  return authorized<CreditEntry[]>(`/billing/entries?limit=${ENTRIES_SHOWN}`, {
    signal,
  });
}

/**
 * Opens a checkout, on Stripe's page, for the pack that gives ``credits``; only an owner may.
 * The answer is the page's address, which the browser goes to.
 */
export async function openCheckout(credits: number): Promise<string> {
  const opened = await authorized<Schemas["CheckoutOut"]>("/billing/checkout", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ credits }),
  });
  return opened.url;
}

/** A pack's price, from cents, in the visitor's language: `10,00 €`. */
export function formatPrice(locale: string, pack: CreditPack): string {
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency: pack.currency.toUpperCase(),
  }).format(pack.price / 100);
}

/** What the page was sent back from Stripe with, if anything: a payment, or none. */
export type Returned = "paid" | "cancelled" | null;

/** What the address ``search`` says the visitor came back from Stripe with. */
export function returnedFrom(search: string): Returned {
  const said = new URLSearchParams(search).get("checkout");
  return said === "paid" || said === "cancelled" ? said : null;
}
