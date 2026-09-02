/**
 * The four analytics tabs, each backed by one /api/dashboard endpoint:
 *   Overview → /trends      (weekly money flow)
 *   Rent     → /collection  (collection efficiency, aging, COD)
 *   Fleet    → /fleet       (per-EV / per-provider economics)
 *   Riders   → /riders      (movement, top earners, sliding into dues)
 *
 * Every chart is paired with the numbers as a table (the aqua palette slot
 * has low contrast on the light surface — the table is the required relief,
 * and operators like copy-pastable numbers anyway).
 */
import { Link } from 'react-router-dom'
import { useApi } from '../../hooks/useApi'
import { Spinner } from '../../components/Spinner'
import { integer, money, moneyWhole, percent } from '../../lib/format'
import { C, DivergingBarChart, HBars, LineChart, StackedBarChart } from './charts'

// ── shared bits ──────────────────────────────────────────────────────────

interface WeekRow {
  week: string
  week_start: string
}

const wkLabel = (w: WeekRow) => w.week_start.slice(5) // MM-DD of the Monday

function qs(companies: string[], weeks: number): string {
  const p = new URLSearchParams({ weeks: String(weeks) })
  if (companies.length) p.set('companies', companies.join(','))
  return '?' + p.toString()
}

export function Panel({
  title,
  subtitle,
  children,
  className = '',
}: {
  title: string
  subtitle?: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <div
      className={`bg-white/80 backdrop-blur-xl rounded-xl shadow-card transition-shadow duration-200 hover:shadow-glass p-4 ${className}`}
    >
      <div className="flex items-baseline justify-between mb-2 gap-3">
        <h3 className="font-semibold">{title}</h3>
        {subtitle && <span className="text-xs text-slate-400 text-right">{subtitle}</span>}
      </div>
      {children}
    </div>
  )
}

function LoadGuard<T>({
  data,
  loading,
  error,
  children,
}: {
  data: T | null
  loading: boolean
  error: string | null
  children: (d: T) => React.ReactNode
}) {
  if (loading && !data) return <Spinner label="Loading analytics…" />
  if (error) return <p role="alert" className="text-rose-600 text-sm p-4">{error}</p>
  if (!data) return null
  return <>{children(data)}</>
}

function NumbersTable({
  columns,
  rows,
}: {
  columns: string[]
  rows: (string | number | null)[][]
}) {
  return (
    <details className="mt-2">
      <summary className="text-xs text-slate-500 cursor-pointer select-none hover:text-slate-700">
        View as table
      </summary>
      <div className="overflow-x-auto mt-2 border rounded">
        <table className="w-full text-xs">
          <thead className="bg-slate-100 text-left">
            <tr>
              {columns.map((c, i) => (
                <th key={c} className={`px-2 py-1.5 font-medium ${i > 0 ? 'text-right' : ''}`}>
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-t">
                {r.map((v, j) => (
                  <td key={j} className={`px-2 py-1 ${j > 0 ? 'text-right font-mono' : ''}`}>
                    {v === null ? '—' : typeof v === 'number' ? money(v) : v}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  )
}

// ── Overview: money flow over time ───────────────────────────────────────

interface TrendWeek extends WeekRow {
  gross_payout: number
  released: number
  rent_charged: number
  rent_collected: number
  rent_missed: number
  arrears_recovered: number
  dues_delta: number
}

export function OverviewTab({ companies, weeks }: { companies: string[]; weeks: number }) {
  const state = useApi<{ weeks: TrendWeek[] }>('/dashboard/trends' + qs(companies, weeks))
  return (
    <LoadGuard {...state}>
      {(d) => {
        const wks = d.weeks
        const labels = wks.map(wkLabel)
        return (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Panel
              title="Money to riders"
              subtitle="gross payout vs cash actually released, per week"
            >
              <LineChart
                labels={labels}
                series={[
                  { key: 'g', label: 'Gross payout', color: C.blue, values: wks.map((w) => w.gross_payout) },
                  { key: 'r', label: 'Released', color: C.aqua, values: wks.map((w) => w.released) },
                ]}
              />
              <p className="text-xs text-slate-400 mt-1">
                The gap between the lines is what was withheld: rent, arrears recovery, COD and
                holds.
              </p>
            </Panel>
            <Panel title="Rent flow" subtitle="charged vs collected vs missed, per week">
              <LineChart
                labels={labels}
                series={[
                  { key: 'c', label: 'Charged', color: C.blue, values: wks.map((w) => w.rent_charged) },
                  { key: 'k', label: 'Collected', color: C.aqua, values: wks.map((w) => w.rent_collected) },
                  { key: 'm', label: 'Missed', color: C.red, values: wks.map((w) => w.rent_missed) },
                ]}
              />
            </Panel>
            <Panel
              title="Arrears recovered"
              subtitle="old missed rent clawed back, per week"
            >
              <LineChart
                labels={labels}
                series={[
                  { key: 'a', label: 'Recovered', color: C.aqua, values: wks.map((w) => w.arrears_recovered) },
                ]}
              />
            </Panel>
            <Panel
              title="Dues movement"
              subtitle="up = riders paid dues down · down = dues grew"
            >
              <DivergingBarChart
                labels={labels}
                values={wks.map((w) => w.dues_delta)}
                posLabel="Paid down"
                negLabel="Dues grew"
              />
            </Panel>
            <Panel title="Weekly numbers" className="lg:col-span-2">
              <NumbersTable
                columns={[
                  'Week',
                  'Gross payout',
                  'Released',
                  'Rent charged',
                  'Collected',
                  'Missed',
                  'Arrears recovered',
                  'Dues Δ',
                ]}
                rows={wks.map((w) => [
                  w.week,
                  w.gross_payout,
                  w.released,
                  w.rent_charged,
                  w.rent_collected,
                  w.rent_missed,
                  w.arrears_recovered,
                  w.dues_delta,
                ])}
              />
            </Panel>
          </div>
        )
      }}
    </LoadGuard>
  )
}

// ── Rent: collection efficiency ──────────────────────────────────────────

interface CollectionWeek extends WeekRow {
  expected: number
  collected: number
  missed: number
  pending: number
  collection_rate: number | null
}
interface CollectionPayload {
  weekly: CollectionWeek[]
  aging: { bucket: string; riders: number; outstanding: number }[]
  velocity_4w: { missed: number; recovered: number }
  cod_exposure: { total_pending: number; riders: number; oldest: string | null }
}

export function RentTab({ companies, weeks }: { companies: string[]; weeks: number }) {
  const state = useApi<CollectionPayload>('/dashboard/collection' + qs(companies, weeks))
  return (
    <LoadGuard {...state}>
      {(d) => {
        const labels = d.weekly.map(wkLabel)
        const net4w = d.velocity_4w.recovered - d.velocity_4w.missed
        return (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Panel
              title="Where every billable day ended up"
              subtitle="collected / missed / awaiting a cycle, per week"
              className="lg:col-span-2"
            >
              <StackedBarChart
                labels={labels}
                series={[
                  { key: 'c', label: 'Collected', color: C.aqua, values: d.weekly.map((w) => w.collected) },
                  { key: 'm', label: 'Missed', color: C.red, values: d.weekly.map((w) => w.missed) },
                  { key: 'p', label: 'Pending', color: C.blue, values: d.weekly.map((w) => w.pending) },
                ]}
              />
              <NumbersTable
                columns={['Week', 'Expected', 'Collected', 'Missed', 'Pending', 'Rate']}
                rows={d.weekly.map((w) => [
                  w.week,
                  w.expected,
                  w.collected,
                  w.missed,
                  w.pending,
                  w.collection_rate === null ? '—' : percent(w.collection_rate),
                ])}
              />
            </Panel>
            <Panel title="Collection rate" subtitle="collected ÷ expected, per week">
              <LineChart
                labels={labels}
                series={[
                  {
                    key: 'r',
                    label: 'Rate',
                    color: C.blue,
                    values: d.weekly.map((w) => w.collection_rate ?? 0),
                  },
                ]}
                format={(v) => percent(v)}
              />
            </Panel>
            <Panel
              title="Arrears aging"
              subtitle="debtors by age of their oldest still-missed day"
            >
              <HBars
                rows={d.aging.map((b) => ({
                  label: b.bucket,
                  value: b.outstanding,
                  note: `${integer(b.riders)} rider${b.riders === 1 ? '' : 's'}`,
                }))}
                format={(v) => '₹' + moneyWhole(v)}
              />
              <p className="text-xs text-slate-400 mt-2">
                Money in the 60d+ bucket rarely comes back on its own — chase those first.
              </p>
            </Panel>
            <Panel title="Recovery velocity — last 4 weeks" subtitle="are arrears shrinking?">
              <div className="grid grid-cols-3 gap-3 text-center">
                <div>
                  <p className="text-xs text-slate-500">Newly missed</p>
                  <p className="text-xl font-bold mt-1">₹{moneyWhole(d.velocity_4w.missed)}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">Recovered</p>
                  <p className="text-xl font-bold mt-1">₹{moneyWhole(d.velocity_4w.recovered)}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">Net</p>
                  <p className={`text-xl font-bold mt-1 ${net4w >= 0 ? 'text-emerald-700' : 'text-rose-700'}`}>
                    {net4w >= 0 ? '−' : '+'}₹{moneyWhole(Math.abs(net4w))}
                  </p>
                  <p className="text-[10px] text-slate-400">
                    {net4w >= 0 ? 'arrears shrinking' : 'arrears growing'}
                  </p>
                </div>
              </div>
            </Panel>
            <Panel title="COD exposure" subtitle="held COD not yet cleared">
              <div className="grid grid-cols-3 gap-3 text-center">
                <div>
                  <p className="text-xs text-slate-500">Outstanding</p>
                  <p className="text-xl font-bold mt-1">
                    ₹{moneyWhole(d.cod_exposure.total_pending)}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">Riders</p>
                  <p className="text-xl font-bold mt-1">{integer(d.cod_exposure.riders)}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">Oldest hold</p>
                  <p className="text-xl font-bold mt-1">{d.cod_exposure.oldest ?? '—'}</p>
                </div>
              </div>
            </Panel>
          </div>
        )
      }}
    </LoadGuard>
  )
}

// ── Fleet: per-EV / per-provider economics ───────────────────────────────

interface FleetEv {
  ev_id: string
  provider: string
  model: string
  holder_person_id: number | null
  holder: string | null
  ledger_days: number
  billable_days: number
  missed_days: number
  maintenance_days: number
  idle_days: number
  utilization: number
  earned: number
  missed: number
  provider_owed: number
  margin: number
}
interface FleetPayload {
  date_from: string
  date_to: string
  providers: {
    provider: string
    evs: number
    earned: number
    missed: number
    provider_owed: number
    margin: number
  }[]
  evs: FleetEv[]
}

export function FleetTab({ dateFrom, dateTo }: { dateFrom: string; dateTo: string }) {
  const p = new URLSearchParams()
  if (dateFrom) p.set('date_from', dateFrom)
  if (dateTo) p.set('date_to', dateTo)
  const state = useApi<FleetPayload>('/dashboard/fleet?' + p.toString())
  return (
    <LoadGuard {...state}>
      {(d) => {
        const losing = d.evs.filter((e) => e.margin < 0)
        return (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Panel
              title="Margin by provider"
              subtitle={`rent earned − provider cost · ${d.date_from} → ${d.date_to}`}
            >
              <HBars
                rows={d.providers.map((pr) => ({
                  label: pr.provider,
                  value: pr.margin,
                  note: `${integer(pr.evs)} EVs`,
                }))}
                format={(v) => (v < 0 ? '−' : '') + '₹' + moneyWhole(Math.abs(v))}
              />
              <p className="text-xs text-slate-400 mt-2">
                Red = the fleet cost more than it earned in this window.
              </p>
            </Panel>
            <Panel title="Earned vs owed by provider" subtitle="the two sides of the margin">
              <HBars
                rows={d.providers.flatMap((pr) => [
                  { label: pr.provider, value: pr.earned, note: 'earned' },
                  { label: '', value: -pr.provider_owed, note: 'owed' },
                ])}
                color={C.aqua}
                format={(v) => (v < 0 ? '−' : '') + '₹' + moneyWhole(Math.abs(v))}
              />
            </Panel>
            <Panel
              title={`Per-EV economics (${d.evs.length} EVs, worst margin first)`}
              subtitle={losing.length ? `${losing.length} losing money in this window` : 'all EVs covering their cost'}
              className="lg:col-span-2"
            >
              <div className="overflow-x-auto overflow-y-auto max-h-[480px] border rounded">
                <table className="w-full text-sm">
                  <thead className="bg-slate-100 text-left sticky top-0 z-10">
                    <tr>
                      <th className="px-3 py-2 text-xs">EV</th>
                      <th className="px-3 py-2 text-xs">Provider</th>
                      <th className="px-3 py-2 text-xs">Holder</th>
                      <th className="px-3 py-2 text-xs text-right">Utilization</th>
                      <th className="px-3 py-2 text-xs text-right">Days b/m/i</th>
                      <th className="px-3 py-2 text-xs text-right">Earned</th>
                      <th className="px-3 py-2 text-xs text-right">Missed</th>
                      <th className="px-3 py-2 text-xs text-right">Provider owed</th>
                      <th className="px-3 py-2 text-xs text-right">Margin</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.evs.length === 0 && (
                      <tr>
                        <td colSpan={9} className="p-6 text-center text-slate-500 text-sm">
                          No ledger activity in this window.
                        </td>
                      </tr>
                    )}
                    {d.evs.map((e) => (
                      <tr key={e.ev_id} className="border-t hover:bg-slate-50">
                        <td className="px-3 py-2">
                          <Link
                            to={'/evs/' + encodeURIComponent(e.ev_id)}
                            className="text-brand underline"
                          >
                            {e.ev_id}
                          </Link>
                          <span className="text-xs text-slate-400 ml-1">{e.model}</span>
                        </td>
                        <td className="px-3 py-2 text-xs">{e.provider}</td>
                        <td className="px-3 py-2 text-xs">
                          {e.holder_person_id ? (
                            <Link to={'/persons/' + e.holder_person_id} className="text-brand underline">
                              {e.holder}
                            </Link>
                          ) : (
                            <span className="text-slate-400">unassigned</span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-right">
                          <div className="inline-flex items-center gap-1.5">
                            <div className="w-14 h-1.5 bg-slate-100 rounded overflow-hidden">
                              <div
                                className="h-full rounded-r"
                                style={{ width: `${e.utilization}%`, background: C.blue }}
                              />
                            </div>
                            <span className="text-xs font-mono">{percent(e.utilization, 0)}</span>
                          </div>
                        </td>
                        <td className="px-3 py-2 text-right text-xs font-mono text-slate-500">
                          {e.billable_days}/{e.missed_days}/{e.idle_days + e.maintenance_days}
                        </td>
                        <td className="px-3 py-2 text-right font-mono">{money(e.earned)}</td>
                        <td className="px-3 py-2 text-right font-mono text-rose-700">
                          {e.missed ? money(e.missed) : '—'}
                        </td>
                        <td className="px-3 py-2 text-right font-mono">{money(e.provider_owed)}</td>
                        <td
                          className={`px-3 py-2 text-right font-mono font-semibold ${e.margin < 0 ? 'text-rose-700' : 'text-emerald-700'}`}
                        >
                          {money(e.margin)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="text-xs text-slate-400 mt-2">
                Days b/m/i = billable / missed / idle+maintenance ledger days in the window.
              </p>
            </Panel>
          </div>
        )
      }}
    </LoadGuard>
  )
}

// ── Riders: movement + leaderboards ──────────────────────────────────────

interface RiderWeek extends WeekRow {
  paid: number
  new: number
  churned: number
}
interface RidersPayload {
  weekly: RiderWeek[]
  top_earners: { person_id: number; display_name: string; released: number; cycles: number }[]
  sliding_into_dues: {
    person_id: number
    display_name: string
    dues_delta: number
    dues: number
  }[]
}

export function RidersTab({ companies, weeks }: { companies: string[]; weeks: number }) {
  const state = useApi<RidersPayload>('/dashboard/riders' + qs(companies, weeks))
  return (
    <LoadGuard {...state}>
      {(d) => {
        // Drop the in-progress week: nobody has been paid "this week" until its
        // cycle runs, so every recent rider would show as a bogus churn spike.
        const wks = d.weekly.length > 1 ? d.weekly.slice(0, -1) : d.weekly
        const labels = wks.map(wkLabel)
        return (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Panel
              title="Rider movement"
              subtitle="paid = got a payout · new = first-ever payout · churned = paid recently, not that week · current week excluded"
              className="lg:col-span-2"
            >
              <LineChart
                labels={labels}
                series={[
                  { key: 'p', label: 'Paid', color: C.blue, values: wks.map((w) => w.paid) },
                  { key: 'n', label: 'New', color: C.aqua, values: wks.map((w) => w.new) },
                  { key: 'c', label: 'Churned', color: C.red, values: wks.map((w) => w.churned) },
                ]}
                format={(v) => integer(v)}
              />
              <NumbersTable
                columns={['Week', 'Paid', 'New', 'Churned']}
                rows={wks.map((w) => [w.week, String(w.paid), String(w.new), String(w.churned)])}
              />
            </Panel>
            <Panel title="Top earners" subtitle="net released in the window">
              <RiderTable
                rows={d.top_earners.map((r) => ({
                  person_id: r.person_id,
                  name: r.display_name,
                  value: r.released,
                  note: `${r.cycles} cycle${r.cycles === 1 ? '' : 's'}`,
                }))}
                valueHeader="Released"
                empty="No releases in this window."
              />
            </Panel>
            <Panel title="Sliding into dues" subtitle="dues grew the most in the window">
              <RiderTable
                rows={d.sliding_into_dues.map((r) => ({
                  person_id: r.person_id,
                  name: r.display_name,
                  value: r.dues_delta,
                  note: `owes ₹${moneyWhole(r.dues)} now`,
                }))}
                valueHeader="Dues added"
                valueClass="text-rose-700"
                empty="Nobody's dues grew in this window. Nice."
              />
            </Panel>
          </div>
        )
      }}
    </LoadGuard>
  )
}

function RiderTable({
  rows,
  valueHeader,
  valueClass = '',
  empty,
}: {
  rows: { person_id: number; name: string; value: number; note: string }[]
  valueHeader: string
  valueClass?: string
  empty: string
}) {
  if (rows.length === 0) return <p className="text-slate-400 text-sm p-4 text-center">{empty}</p>
  return (
    <table className="w-full text-sm">
      <thead className="bg-slate-100 text-left">
        <tr>
          <th className="px-3 py-2 text-xs">#</th>
          <th className="px-3 py-2 text-xs">Rider</th>
          <th className="px-3 py-2 text-xs text-right">{valueHeader}</th>
          <th className="px-3 py-2 text-xs text-right">·</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={r.person_id} className="border-t hover:bg-slate-50">
            <td className="px-3 py-2 text-xs text-slate-500">{i + 1}</td>
            <td className="px-3 py-2">
              <Link to={'/persons/' + r.person_id} className="text-brand underline">
                {r.name}
              </Link>
            </td>
            <td className={`px-3 py-2 text-right font-mono ${valueClass}`}>{money(r.value)}</td>
            <td className="px-3 py-2 text-right text-xs text-slate-400 whitespace-nowrap">
              {r.note}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
