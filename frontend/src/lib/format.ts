/**
 * Number formatting. The API already converts paise to rupees at its edge, so
 * every money value the UI sees is rupees. Always Indian grouping (1,25,000),
 * regardless of the operator's browser locale — 12 of the 13 per-page
 * formatters used `toLocaleString(undefined, …)` and rendered 125,000 on an
 * en-US browser.
 */

const INR = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const INR0 = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 })
const INT = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 })

/** `1,25,000.00` */
export function money(n: number | null | undefined): string {
  return INR.format(n ?? 0)
}

/** `₹1,25,000.00` */
export function rupees(n: number | null | undefined): string {
  return '₹' + money(n)
}

/** `1,25,000` — for totals and stat tiles where paise are noise. */
export function moneyWhole(n: number | null | undefined): string {
  return INR0.format(n ?? 0)
}

export function integer(n: number | null | undefined): string {
  return INT.format(n ?? 0)
}

export function percent(n: number | null | undefined, digits = 1): string {
  return `${(n ?? 0).toFixed(digits)}%`
}
