/**
 * Local-time date helpers for ISO `YYYY-MM-DD` strings.
 *
 * Everything here works in the browser's local timezone. The old helpers in
 * ProviderPage parsed `iso + 'T00:00:00'` as LOCAL time and then read it back
 * with `getUTCDate()/toISOString()`, which for anyone in India (UTC+5:30)
 * moved every date one day back and put "this week" a week early. Never mix
 * `toISOString()` (UTC) with a local date.
 */

const pad = (n: number) => String(n).padStart(2, '0')

/** Format a Date as local `YYYY-MM-DD`. */
export function toISODate(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** Parse `YYYY-MM-DD` as local midnight. */
export function fromISODate(iso: string): Date {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  return new Date(y, (m ?? 1) - 1, d ?? 1)
}

/** Today's local date as `YYYY-MM-DD`. */
export function todayISO(): string {
  return toISODate(new Date())
}

export function addDaysISO(iso: string, days: number): string {
  const d = fromISODate(iso)
  d.setDate(d.getDate() + days)
  return toISODate(d)
}

export function addMonthsISO(iso: string, months: number): string {
  const d = fromISODate(iso)
  d.setMonth(d.getMonth() + months)
  return toISODate(d)
}

/** 0 = Sunday … 6 = Saturday, in local time. */
export function weekday(iso: string): number {
  return fromISODate(iso).getDay()
}

/** Monday of the week containing `iso`. */
export function startOfWeekISO(iso: string, weekStartsOn: 0 | 1 = 1): string {
  const wd = weekday(iso)
  const back = (wd - weekStartsOn + 7) % 7
  return addDaysISO(iso, -back)
}

export function startOfMonthISO(iso: string): string {
  return iso.slice(0, 7) + '-01'
}

export function endOfMonthISO(iso: string): string {
  const d = fromISODate(iso)
  return toISODate(new Date(d.getFullYear(), d.getMonth() + 1, 0))
}

/** Inclusive day count between two ISO dates. */
export function daysBetweenISO(from: string, to: string): number {
  const ms = fromISODate(to).getTime() - fromISODate(from).getTime()
  return Math.round(ms / 86_400_000) + 1
}
