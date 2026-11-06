/**
 * Amounts and dates as an invoice states them, written the way the visitor's language writes
 * them.
 */

/**
 * An amount, which the API sends as a decimal string, in its currency when the invoice names
 * one. Every digit is kept: the string is formatted as it is, not as a floating-point number,
 * with all its decimals and at least two. A currency's usual decimals are not imposed, since
 * they differ between versions of the browsers' data (the dinar's are 0 in some, 2 in others),
 * and rounding an invoice's amount would show one it does not state.
 */
export function formatAmount(
  locale: string,
  amount: string,
  currency: string | null,
): string {
  const decimals = Math.max(2, amount.split(".")[1]?.length ?? 0);
  return new Intl.NumberFormat(locale, {
    ...(currency ? { style: "currency", currency } : {}),
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(amount as Intl.StringNumericLiteral);
}

/** A calendar day, `2026-11-06`, which is the same day wherever the visitor is. */
export function formatDay(locale: string, day: string): string {
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeZone: "UTC",
  }).format(new Date(`${day}T00:00:00Z`));
}

/** A moment, as the API sends it in ISO 8601, in Belgrade's time. */
export function formatMoment(locale: string, moment: string): string {
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Europe/Belgrade",
  }).format(new Date(moment));
}
