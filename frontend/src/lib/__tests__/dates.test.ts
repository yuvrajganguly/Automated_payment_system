/**
 * Runs under TZ=Asia/Kolkata (see vitest.config.ts) — the timezone every
 * operator of this system is in, and the one where the old UTC-mixing helpers
 * moved dates back a day.
 */
import { describe, expect, it, vi, afterEach } from 'vitest'
import {
  addDaysISO, addMonthsISO, daysBetweenISO, endOfMonthISO, fromISODate,
  startOfMonthISO, startOfWeekISO, toISODate, todayISO, weekday,
} from '../dates'

afterEach(() => vi.useRealTimers())

describe('dates (local time)', () => {
  it('round-trips an ISO date without drifting', () => {
    expect(toISODate(fromISODate('2026-09-01'))).toBe('2026-09-01')
    expect(addDaysISO('2026-09-01', 0)).toBe('2026-09-01')   // was 2026-08-31 in IST
  })

  it('adds days across month and year ends', () => {
    expect(addDaysISO('2026-08-31', 1)).toBe('2026-09-01')
    expect(addDaysISO('2026-12-31', 1)).toBe('2027-01-01')
    expect(addDaysISO('2026-03-01', -1)).toBe('2026-02-28')
  })

  it('knows the weekday and the Monday of the week', () => {
    expect(weekday('2026-09-01')).toBe(2)                     // Tuesday
    expect(startOfWeekISO('2026-09-01')).toBe('2026-08-31')   // Monday
    expect(startOfWeekISO('2026-08-31')).toBe('2026-08-31')
    expect(startOfWeekISO('2026-09-06')).toBe('2026-08-31')   // Sunday belongs to the week before
  })

  it('month helpers', () => {
    expect(startOfMonthISO('2026-09-17')).toBe('2026-09-01')
    expect(endOfMonthISO('2026-02-10')).toBe('2026-02-28')
    expect(endOfMonthISO('2028-02-10')).toBe('2028-02-29')
    expect(addMonthsISO('2026-09-01', -3)).toBe('2026-06-01')
  })

  it('inclusive day counts', () => {
    expect(daysBetweenISO('2026-08-24', '2026-08-30')).toBe(7)
  })

  it('todayISO is the local calendar day, even just after local midnight', () => {
    // 00:30 IST on 1 Sep = 19:00 UTC on 31 Aug. The UTC-based helper said "31 Aug".
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-31T19:00:00Z'))
    expect(todayISO()).toBe('2026-09-01')
  })

  it('ProviderPage default weekly range: previous Monday..Sunday', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-01T03:30:00Z'))      // Tue 1 Sep, 09:00 IST
    const monday = addDaysISO(startOfWeekISO(todayISO()), -7)
    expect([monday, addDaysISO(monday, 6)]).toEqual(['2026-08-24', '2026-08-30'])
    // the old implementation produced 2026-08-17 .. 2026-08-22
  })
})
