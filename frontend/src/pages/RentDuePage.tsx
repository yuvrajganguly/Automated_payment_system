import { useState } from 'react'
import { api, saveBlob } from '../api/client'
import { useApi } from '../hooks/useApi'
import { useAuth } from '../auth/AuthContext'
import { Spinner } from '../components/Spinner'
import { money } from '../lib/format'

/** Weekly EV rent for riders no payout will ever cover (Zomato, Elastic…).
 *  A rider owes rent for holding the vehicle, not for working, so this page
 *  books the week for every direct-pay holder as RENT_DUE — arrears from day
 *  one, recovered by a cash receipt on the person page — and prints the
 *  sheet the hubs collect against. */

type Entry = {
  person_id: number
  name: string
  ev_id: string
  rider_id: string
  company: string
  hub: string | null
  mob_no: string | null
  weekly_rate: number
  day_from: string
  day_to: string
  days: number
  amount: number
  arrears_outstanding: number
  already_booked: boolean
}
type Preview = {
  week_start: string
  week_end: string
  entries: Entry[]
  pending_count: number
  amount: number
  booked_count: number
}

/** The most recent completed Sunday (weeks run Monday..Sunday, as the provider bills them). */
function lastSunday(from = new Date()): string {
  const d = new Date(from)
  d.setDate(d.getDate() - (d.getDay() === 0 ? 7 : d.getDay()))
  const y = d.getFullYear(), m = String(d.getMonth() + 1).padStart(2, '0'), dd = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${dd}`
}

export function RentDuePage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin' || user?.role === 'creator'
  const [weekEnd, setWeekEnd] = useState(lastSunday())
  const { data, error, loading, reload } = useApi<Preview>(`/rent-due/preview?week_end=${weekEnd}`, [weekEnd])
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)

  async function book() {
    if (!data) return
    if (!window.confirm(
      `Book ${data.pending_count} rider${data.pending_count === 1 ? '' : 's'} — ₹${money(data.amount)} of rent for ` +
      `${data.week_start} to ${data.week_end} — to EV arrears as due? Nothing is deducted; it is collected in cash.`,
    )) return
    setBusy(true); setMsg(null)
    try {
      const r = await api.post<{ count: number; amount: number }>('/rent-due/book', { week_end: weekEnd })
      setMsg(`Booked ${r.count} rider${r.count === 1 ? '' : 's'}, ₹${money(r.amount)}.`)
      reload()
    } catch (e) {
      setMsg(e instanceof Error ? e.message : 'Failed')
    } finally { setBusy(false) }
  }

  async function sheet() {
    setBusy(true)
    try {
      saveBlob(await api.download('/rent-due/collection', {
        json: { week_end: weekEnd }, fallbackName: `rent_collection_${weekEnd}.xlsx`,
      }))
    } catch (e) {
      setMsg(e instanceof Error ? e.message : 'Failed')
    } finally { setBusy(false) }
  }

  return (
    <div>
      <div className="flex flex-wrap items-end gap-3 mb-4">
        <div>
          <h1 className="text-xl font-semibold">Rent due — direct-pay riders</h1>
          <p className="text-xs text-slate-500 max-w-2xl">
            Riders whose company pays them directly never come through a payout, so no cycle charges
            their EV rent. This books the week for every such holder as rent due (arrears from day one)
            and prints the sheet the hubs collect against. Cash received is recorded on the rider's page.
          </p>
        </div>
        <label className="block text-sm ml-auto">
          <span className="block text-xs">Week ending (Sunday)</span>
          <input type="date" value={weekEnd} onChange={(e) => setWeekEnd(e.target.value)}
                 className="border rounded px-3 py-1.5" />
        </label>
      </div>

      {loading && <Spinner />}
      {error && <div className="text-red-400 text-sm">{error}</div>}
      {data && (
        <>
          <div className="flex flex-wrap items-center gap-3 mb-3">
            <div className="panel px-4 py-2 text-sm">
              <span className="text-slate-500">To book</span>{' '}
              <b>{data.pending_count}</b> rider{data.pending_count === 1 ? '' : 's'} · <b>₹{money(data.amount)}</b>
              {data.booked_count > 0 && <span className="text-slate-500"> · {data.booked_count} already booked</span>}
            </div>
            {isAdmin && (
              <button onClick={book} disabled={busy || data.pending_count === 0}
                      className="bg-amber-600 hover:bg-amber-500 text-white px-3 py-1.5 rounded disabled:opacity-50">
                {busy ? 'Working…' : `Book ${data.week_start} → ${data.week_end}`}
              </button>
            )}
            <button onClick={sheet} disabled={busy || data.entries.length === 0}
                    className="border px-3 py-1.5 rounded disabled:opacity-50">
              Collection sheet (.xlsx)
            </button>
            {msg && <span className="text-xs text-slate-400">{msg}</span>}
          </div>

          {data.entries.length === 0 ? (
            <div className="text-sm text-slate-500">
              Nobody owes rent outside a payout for this week.
            </div>
          ) : (
            <div className="panel overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-slate-500">
                    <th className="px-3 py-2">Rider</th>
                    <th className="px-3 py-2">Company</th>
                    <th className="px-3 py-2">Hub</th>
                    <th className="px-3 py-2">EV</th>
                    <th className="px-3 py-2">Days</th>
                    <th className="px-3 py-2 text-right">Rent</th>
                    <th className="px-3 py-2 text-right">Arrears</th>
                    <th className="px-3 py-2">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {data.entries.map((e) => (
                    <tr key={e.ev_id + e.person_id} className="border-t border-slate-800/40">
                      <td className="px-3 py-2">
                        <a href={`/persons/${e.person_id}`} className="underline">{e.name}</a>
                        <span className="text-xs text-slate-500"> · {e.rider_id}</span>
                      </td>
                      <td className="px-3 py-2">{e.company}</td>
                      <td className="px-3 py-2">{e.hub ?? '—'}</td>
                      <td className="px-3 py-2 font-mono text-xs">{e.ev_id}</td>
                      <td className="px-3 py-2">{e.days} <span className="text-xs text-slate-500">({e.day_from.slice(5)}→{e.day_to.slice(5)})</span></td>
                      <td className="px-3 py-2 text-right">₹{money(e.amount)}</td>
                      <td className="px-3 py-2 text-right">₹{money(e.arrears_outstanding)}</td>
                      <td className="px-3 py-2 text-xs">
                        {e.already_booked
                          ? <span className="text-emerald-300">booked</span>
                          : <span className="text-amber-300">to book</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}
