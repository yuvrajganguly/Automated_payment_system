/**
 * Company page — one company's complete history, cycle by cycle.
 *
 * Reached by clicking a company on the Dashboard's Companies tab. The
 * header carries lifetime totals; the table below is every payout cycle
 * ever processed for the company, newest first, with the week's reconciling
 * numbers: what came in, what the rent did, old dues recovered out of the
 * payout, and what riders still carried out of it. Not window-scoped.
 */
import { Link, useParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { Spinner } from '../components/Spinner'
import { moneyWhole } from '../lib/format'

interface Header {
  company_name: string
  orders_column: string | null
  rider_ids_shared_with: string | null
  is_active: number
  payment_model: 'payout_file' | 'per_order' | 'direct' | null
  cadence: string | null
  per_order_rate: number | null
  notes: string | null
  riders: number
  cycles: number
  first_cycle: string | null
  last_cycle: string | null
  gross_payout: number
  released: number
  rent_collected: number
  rent_missed: number
  arrears_recovered: number
  prior_dues_collected: number
  written_off: number
  active_riders: number
  rider_ids: number
}
interface WeekRow {
  company: string
  cycle_start: string
  cycle_end: string
  riders: number
  gross_payout: number
  released: number
  rent_charged: number
  rent_collected: number
  rent_missed: number
  arrears_recovered: number
  prior_dues_collected: number
  dues_added: number
  carried_forward: number
  written_off: number
  cod_held: number
  partial: boolean
}

const r0 = (n: number | null | undefined) => '₹' + moneyWhole(n ?? 0)
const cell = 'px-3 py-2 text-right tabular-nums whitespace-nowrap'
const cellL = 'px-3 py-2 whitespace-nowrap'

export function CompanyPage() {
  const { name = '' } = useParams<{ name: string }>()
  const enc = encodeURIComponent(name)
  const head = useApi<Header>('/dashboard/story/company/' + enc)
  const weeks = useApi<{ rows: WeekRow[] }>('/dashboard/story/weeks?all_time=1&companies=' + enc)

  if (head.loading && !head.data) return <Spinner label="Loading…" />
  if (head.error || !head.data) return <p className="text-red-400">{head.error ?? 'Not found'}</p>
  const h = head.data
  const rows = weeks.data?.rows ?? []
  const charged = h.rent_collected + h.rent_missed
  const span = h.first_cycle && h.last_cycle ? `${h.first_cycle} → ${h.last_cycle}` : 'no cycles yet'

  return (
    <div className="max-w-6xl mx-auto">
      <div className="flex flex-wrap gap-4 text-sm">
        <Link to="/dashboard?tab=companies" className="text-brand underline">← Back to Companies</Link>
        <Link to="/companies" className="text-slate-500 hover:text-brand-300">Manage companies</Link>
      </div>
      <h1 className="text-2xl font-bold mt-2 mb-1">
        {h.company_name}
        {!h.is_active && <span className="ml-2 text-xs bg-slate-500/20 text-slate-500 px-2 py-0.5 rounded align-middle">inactive</span>}
      </h1>
      <p className="text-sm text-slate-500 mb-5">
        {h.cycles} payout cycle{h.cycles === 1 ? '' : 's'} · {span} · {h.riders} rider{h.riders === 1 ? '' : 's'} ever paid
        · {h.active_riders} of {h.rider_ids} rider id{h.rider_ids === 1 ? '' : 's'} active
        {h.rider_ids_shared_with && <> · shares rider ids with {h.rider_ids_shared_with}</>}
        {h.notes && <span className="block text-slate-400 mt-0.5">{h.notes}</span>}
      </p>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-8">
        <Stat label="Came in" value={r0(h.gross_payout)} hint="all payouts ever received" />
        <Stat label="Paid out" value={r0(h.released)} hint="released to riders" />
        <Stat label="Rent collected" value={r0(h.rent_collected)}
              hint={charged > 0 ? `${Math.round((h.rent_collected / charged) * 100)}% of rent charged` : 'no rent charged'}
              tone="text-emerald-300" />
        <Stat label="Rent missed" value={r0(h.rent_missed)} hint="not covered by the payout" tone={h.rent_missed > 0 ? 'text-red-300' : ''} />
        <Stat label="Clawed back" value={r0(h.arrears_recovered)} hint="rent arrears recovered later" />
        <Stat label="Prior dues collected" value={r0(h.prior_dues_collected)} hint="old debt recovered from payouts" />
        <Stat label="Written off" value={r0(h.written_off)} hint="rent reversed / waived" />
        {h.payment_model === 'per_order' ? (
          <Stat label="How they pay" value={`₹${h.per_order_rate ?? 0} / order, paid by us`} hint="order counts typed on Process Payout" small />
        ) : h.payment_model === 'direct' ? (
          <Stat label="How they pay" value="Riders paid directly" hint="roster only — nothing to process" small />
        ) : (
          <Stat label="Orders column" value={h.orders_column || '—'} hint="as read from their file" small />
        )}
      </div>

      <h2 className="font-semibold mb-1">Week by week</h2>
      <p className="text-sm text-slate-500 mb-3">
        Every cycle processed for {h.company_name}, newest first.
        <span className="text-slate-400"> "Prior dues collected" is old debt recovered out of that payout; "Carried forward" is what riders still owed after it.</span>
      </p>
      {weeks.error ? (
        <p className="text-red-400">{weeks.error}</p>
      ) : weeks.loading && !weeks.data ? (
        <Spinner label="Loading cycles…" />
      ) : rows.length === 0 ? (
        <p className="text-sm text-slate-500 panel p-4">No payout has been processed for this company yet.</p>
      ) : (
        <div className="panel overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left border-b border-edge-soft">
              <tr>
                <th className={cellL + ' font-medium text-xs'}>Cycle</th>
                <th className={cell + ' font-medium text-xs'}>Riders</th>
                <th className={cell + ' font-medium text-xs'}>Came in</th>
                <th className={cell + ' font-medium text-xs'}>Rent collected</th>
                <th className={cell + ' font-medium text-xs'}>Rent missed</th>
                <th className={cell + ' font-medium text-xs'}>Clawed back</th>
                <th className={cell + ' font-medium text-xs'}>Prior dues collected</th>
                <th className={cell + ' font-medium text-xs'}>COD held</th>
                <th className={cell + ' font-medium text-xs'}>Paid out</th>
                <th className={cell + ' font-medium text-xs'}>Dues added</th>
                <th className={cell + ' font-medium text-xs'}>Carried forward</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.cycle_start + r.cycle_end} className="border-t border-edge-soft hover:bg-white/[0.02]">
                  <td className={cellL + ' text-slate-800'}>{r.cycle_start} → {r.cycle_end}</td>
                  <td className={cell}>{r.riders}</td>
                  <td className={cell}>{r0(r.gross_payout)}</td>
                  <td className={cell + ' text-emerald-300'}>{r0(r.rent_collected)}</td>
                  <td className={cell + (r.rent_missed > 0 ? ' text-red-300' : '')}>{r0(r.rent_missed)}</td>
                  <td className={cell}>{r0(r.arrears_recovered)}</td>
                  <td className={cell}>{r0(r.prior_dues_collected)}</td>
                  <td className={cell}>{r0(r.cod_held)}</td>
                  <td className={cell}>{r0(r.released)}</td>
                  <td className={cell + (r.dues_added > 0 ? ' text-amber-300' : '')}>{r0(r.dues_added)}</td>
                  <td className={cell + (r.carried_forward > 0 ? ' text-amber-300' : '')}>{r0(r.carried_forward)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t border-edge text-slate-900 font-semibold bg-white/[0.02]">
                <td className={cellL}>All {rows.length} cycles</td>
                <td className={cell + ' text-slate-500 font-normal'}>—</td>
                <td className={cell}>{r0(sum(rows, 'gross_payout'))}</td>
                <td className={cell}>{r0(sum(rows, 'rent_collected'))}</td>
                <td className={cell}>{r0(sum(rows, 'rent_missed'))}</td>
                <td className={cell}>{r0(sum(rows, 'arrears_recovered'))}</td>
                <td className={cell}>{r0(sum(rows, 'prior_dues_collected'))}</td>
                <td className={cell}>{r0(sum(rows, 'cod_held'))}</td>
                <td className={cell}>{r0(sum(rows, 'released'))}</td>
                <td className={cell}>{r0(sum(rows, 'dues_added'))}</td>
                <td className={cell} title="Still carried after the latest cycle">{r0(rows[0]?.carried_forward ?? 0)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </div>
  )
}

const sum = (xs: WeekRow[], k: keyof WeekRow) => xs.reduce((a, r) => a + (r[k] as number), 0)

function Stat({ label, value, hint, tone = '', small = false }:
  { label: string; value: string; hint?: string; tone?: string; small?: boolean }) {
  return (
    <div className="panel p-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className={(small ? 'text-base' : 'text-xl') + ' font-semibold tabular-nums ' + tone}>{value}</div>
      {hint && <div className="text-[11px] text-slate-400 mt-0.5">{hint}</div>}
    </div>
  )
}
