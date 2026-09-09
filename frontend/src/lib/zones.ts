/**
 * Zones — one definition, because two would drift.
 *
 * A store's zone decides which recruiter sees the work there: since the 2026-09
 * fence, field staff are served their own zone and nothing else. A store nobody
 * has classified belongs to everybody until it belongs to someone, which keeps
 * it visible rather than orphaned — but it is still a store nobody owns, so
 * every list that shows zones flags the unassigned ones in red.
 */
export type Zone = 'North' | 'South' | 'Misc'

export const ZONES: Zone[] = ['North', 'South', 'Misc']

export const ZONE_TONE: Record<Zone, string> = {
  North: 'bg-sky-500 text-white border-sky-500',
  South: 'bg-amber-500 text-white border-amber-500',
  Misc: 'bg-slate-500 text-white border-slate-500',
}
