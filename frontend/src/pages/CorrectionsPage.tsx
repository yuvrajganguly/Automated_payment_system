import { useState } from 'react'
import { useUrlString } from '../state/useUrlState'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { useApi } from '../hooks/useApi'
import { Spinner } from '../components/Spinner'
import { rupees } from '../lib/format'

/**
 * Corrections — the fix-it desk.
 *
 * Top: suspected returns (EV holders who vanished from payouts while rent
 * kept piling up) with a one-click backdated return that heals the books.
 * Below: the running log of every manual change — adjustments, manual rent
 * payments, reversals — so "what did we patch, when, and who did it" is one
 * page, not an archaeology session in Transactions.
 */

interface Suspect {
  person_id: number
  display_name: string
  rider_id: string | null
  company: string | null
  ev_id: string
  model: string | null
  weekly_rate: number
  last_payout_end: string | null
  missed_cycles: number
  missed_since: string | null
  missed_amount: number
  arrears_outstanding: number
  suggested_return_date: string | null
}

interface Correction {
  id: number
  person_id: number
  display_name: string
  rider_id: string | null
  company: string | null
  cycle_start: string
  cycle_end: string
  event_type: string
  amount: number
  balance_after: number
  days: number | null
  remarks: string | null
  created_at: string
  created_by: string | null
}

const EVENT_TONE: Record<string, string> = {
  DEPOSIT_APPLIED: 'bg-teal-500/15 text-teal-300',
  ADJUSTMENT: 'bg-brand-50 text-brand-700',
  RENT_REVERSAL: 'bg-amber-500/10 text-amber-300',
  RENT_WAIVED: 'bg-emerald-500/10 text-emerald-300',
  OPENING: 'bg-slate-100 text-slate-600',
  RENT_RECOVERED: 'bg-emerald-500/10 text-emerald-300',
  RENT_COLLECTED: 'bg-emerald-500/10 text-emerald-300',
}

function SuspectRow({ s, onDone }: { s: Suspect; onDone: () => void }) {
  const [date, setDate] = useState(s.suggested_return_date ?? '')
  const [busy, setBusy] = useState<'return' | 'spare' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<string | null>(null)

  const act = async (kind: 'return' | 'spare') => {
    if (!date) { setError('Pick the real return date first.'); return }
    setBusy(kind); setError(null)
    try {
      const path = kind === 'return' ? '/evs/return' : '/evs/to-spare'
      const r = await api.post<{ heal?: { refunded: number; arrears_written_off: number; days_reversed: number } }>(
        path, { ev_id: s.ev_id, returned_date: date })
      const h = r.heal
      setResult(h && h.days_reversed > 0
        ? `Done — ${h.days_reversed} day(s) reversed: ${rupees(h.arrears_written_off)} arrears written off, ${rupees(h.refunded)} refunded.`
        : 'Done — nothing needed reversing.')
      setTimeout(onDone, 2500)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="px-4 py-3 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-slate-100 first:border-t-0">
      <div className="min-w-[200px]">
        <Link to={`/persons/${s.person_id}`} className="font-medium text-slate-900 hover:text-brand-600">
          {s.display_name}
        </Link>
        <div className="text-xs text-slate-500">
          {s.rider_id ? `${s.rider_id}@${s.company ?? '?'}` : `#${s.person_id}`} ·{' '}
          <Link to={`/evs/${s.ev_id}`} className="hover:text-brand-600">{s.ev_id}</Link>
          {s.model ? ` (${s.model})` : ''}
        </div>
      </div>
      <div className="text-sm text-slate-600 flex-1 min-w-[220px]">
        <span className="font-semibold text-critical">{s.missed_cycles} cycles</span> of rent missed
        {s.missed_since ? <> since <span className="font-medium">{s.missed_since}</span></> : null}
        {' — '}{rupees(s.missed_amount)}
        {s.last_payout_end ? <span className="text-slate-400"> · last payout {s.last_payout_end}</span> : null}
      </div>
      {result ? (
        <div className="text-sm text-emerald-300">{result}</div>
      ) : (
        <div className="flex items-center gap-2">
          <label className="text-xs text-slate-500">Returned on</label>
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)}
                 className="border border-slate-300 rounded-lg px-2 py-1 text-sm" />
          <button onClick={() => act('return')} disabled={busy !== null} className="btn-primary">
            {busy === 'return' ? '…' : 'Returned to provider'}
          </button>
          <button onClick={() => act('spare')} disabled={busy !== null} className="btn-ghost">
            {busy === 'spare' ? '…' : 'Back as spare'}
          </button>
        </div>
      )}
      {error && <div className="w-full text-sm text-critical">{error}</div>}
    </div>
  )
}

export function CorrectionsPage() {
  const suspects = useApi<Suspect[]>('/evs/suspected-returns')
  const [eventType, setEventType] = useUrlString('type')
  const feed = useApi<Correction[]>(
    `/corrections?limit=200${eventType ? `&event_type=${eventType}` : ''}`,
    [eventType],
  )

  return (
    <div className="max-w-6xl mx-auto">
      <h1 className="page-title mb-1">Corrections</h1>
      <p className="text-slate-500 text-sm mb-6">
        Suspected EV returns to confirm, and the log of every manual change to the books.
      </p>

      <section className="panel mb-6 overflow-hidden">
        <div className="px-4 py-3 flex items-center justify-between bg-slate-50/60 border-b border-slate-100">
          <h2 className="font-semibold text-slate-800 text-sm">Suspected returns</h2>
          <span className="text-xs text-slate-500">
            EV holders absent from payouts 2+ cycles — recording the real return date reverses the
            wrongly-charged rent automatically
          </span>
        </div>
        {suspects.loading ? (
          <div className="p-6"><Spinner /></div>
        ) : suspects.error ? (
          <div className="p-4 text-sm text-critical">{suspects.error}</div>
        ) : !suspects.data?.length ? (
          <div className="p-4 text-sm text-slate-500">
            Nothing suspicious — every EV holder is showing up in payouts.
          </div>
        ) : (
          suspects.data.map((s) => <SuspectRow key={s.ev_id} s={s} onDone={() => { suspects.reload(); feed.reload() }} />)
        )}
      </section>

      <section className="panel overflow-hidden">
        <div className="px-4 py-3 flex items-center justify-between gap-3 bg-slate-50/60 border-b border-slate-100">
          <h2 className="font-semibold text-slate-800 text-sm">Manual changes</h2>
          <select value={eventType} onChange={(e) => setEventType(e.target.value)}
                  className="border border-slate-300 rounded-lg px-2 py-1 text-xs bg-panel">
            <option value="">All types</option>
            <option value="ADJUSTMENT">Adjustments</option>
            <option value="RENT_REVERSAL">Arrears reversals</option>
            <option value="RENT_WAIVED">Last billed day set</option>
            <option value="DEPOSIT_APPLIED">Deposit applied</option>
            <option value="RENT_RECOVERED">Manual rent — arrears</option>
            <option value="RENT_COLLECTED">Manual rent — current</option>
            <option value="OPENING">Opening balances</option>
          </select>
        </div>
        {feed.loading ? (
          <div className="p-6"><Spinner /></div>
        ) : feed.error ? (
          <div className="p-4 text-sm text-critical">{feed.error}</div>
        ) : !feed.data?.length ? (
          <div className="p-4 text-sm text-slate-500">No manual changes recorded yet.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-slate-500 border-b border-slate-100">
                  <th className="px-4 py-2 font-medium">When</th>
                  <th className="px-4 py-2 font-medium">Person</th>
                  <th className="px-4 py-2 font-medium">Type</th>
                  <th className="px-4 py-2 font-medium text-right">Amount</th>
                  <th className="px-4 py-2 font-medium">Remarks</th>
                  <th className="px-4 py-2 font-medium">By</th>
                </tr>
              </thead>
              <tbody>
                {feed.data.map((c) => (
                  <tr key={c.id} className="border-b border-slate-50 hover:bg-slate-50/50">
                    <td className="px-4 py-2 whitespace-nowrap text-slate-500 text-xs">
                      {(c.created_at ?? '').slice(0, 16)}
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap">
                      <Link to={`/persons/${c.person_id}`} className="text-slate-800 hover:text-brand-600">
                        {c.display_name}
                      </Link>
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap">
                      <span className={`pill ${EVENT_TONE[c.event_type] ?? 'bg-slate-100 text-slate-600'}`}>
                        {c.event_type}
                      </span>
                    </td>
                    <td className={`px-4 py-2 text-right tabular-nums whitespace-nowrap ${
                      c.amount < 0 ? 'text-critical' : 'text-slate-800'}`}>
                      {rupees(c.amount)}
                    </td>
                    <td className="px-4 py-2 text-slate-600 max-w-md truncate" title={c.remarks ?? ''}>
                      {c.remarks}
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap text-xs text-slate-500">{c.created_by}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
