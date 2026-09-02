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

// ── backdated-return healing ─────────────────────────────────────────────
export interface HealSummary {
  refunded: number
  arrears_written_off: number
  days_reversed: number
  offset_applied: number
  deposit_applied?: number
}

/** Human note for a backdated return's automatic book-healing ('' if none). */
export function healNote(h: HealSummary | undefined | null): string {
  if (!h) return ''
  const parts: string[] = []
  if (h.arrears_written_off > 0) parts.push(rupees(h.arrears_written_off) + ' arrears written off')
  if (h.refunded > 0) parts.push(rupees(h.refunded) + ' refunded to balance')
  const rev = h.days_reversed
    ? ` — ${h.days_reversed} wrongly-charged day(s) reversed` + (parts.length ? ': ' + parts.join(', ') : '')
    : ''
  const dep = (h.deposit_applied ?? 0) > 0
    ? ` — security deposit covered ${rupees(h.deposit_applied)} of dues`
    : ''
  return rev + dep
}
