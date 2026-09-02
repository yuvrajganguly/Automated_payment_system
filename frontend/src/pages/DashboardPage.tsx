/**
 * Dashboard — KPI strip + four analytics tabs.
 *
 *   Overview → weekly money-flow trends + secondary metrics + recent cycles
 *   Rent     → collection efficiency, arrears aging, recovery velocity, COD
 *   Fleet    → per-EV / per-provider economics (earned vs provider cost)
 *   Riders   → movement (paid / new / churned), top earners, growing dues
 *
 * The KPI strip is scoped by the company chips + date range and every card
 * opens a drawer with the underlying rows (GET /dashboard/breakdown/*).
 * The weekly tabs use the "Weeks" selector; Fleet uses the date range.
 */
import { useState } from 'react'
import { useUrlList, useUrlString } from '../state/useUrlState'
import { api, saveBlob } from '../api/client'
import { useApi } from '../hooks/useApi'
import { Spinner } from '../components/Spinner'
import { integer, money, moneyWhole } from '../lib/format'
import { addDaysISO, startOfWeekISO, todayISO } from '../lib/dates'
import { Link } from 'react-router-dom'
import { FleetTab, OverviewTab, Panel, RentTab, RidersTab } from './dashboard/analyticsTabs'

// ── /summary types (KPI strip) ───────────────────────────────────────────
interface WeekOption {
  week_bucket: string
  companies: string
  earliest_start: string
  latest_end: string
}
interface Stats {
  active_riders: number
  inactive_riders: number
  active_evs: number
  inactive_evs: number
  untouched_evs: number
  rent_expected: number
  rent_collected: number
  rent_missed: number
  rent_pending: number
  rent_partial: number
  arrears_recovered: number
  total_arrears: number
  manual_rent: number
  cod: number
  hold: number
  payout: number
  provider_owed: number
}
interface Summary {
  filter: {
    company: string | null
    companies: string[]
    date_from: string
    date_to: string
    available_companies: string[]
    available_weeks: WeekOption[]
  }
  window: { from: string; to: string; days: number }
  stats: Stats
  lifetime: { total_riders: number; total_evs: number; total_payout: number }
  recent_cycle_per_company: {
    company: string
    cycle_start: string
    cycle_end: string
    week_bucket: string
    rider_count: number
    total_release: number
    total_rent_charged: number
    total_rent_collected: number
    total_rent_missed: number
    processed_at: string
  }[]
}
interface Breakdown {
  metric: string
  title: string
  columns: string[]
  rows: Record<string, unknown>[]
}

const TABS = [
  ['overview', 'Overview'],
  ['rent', 'Rent'],
  ['fleet', 'Fleet'],
  ['riders', 'Riders'],
] as const

// ── page ─────────────────────────────────────────────────────────────────
/** "Needs attention" — suspected EV returns surface here, linking to the
 *  Corrections fix-it desk. Renders nothing when all is well. */
function AttentionStrip() {
  const { data } = useApi<{ ev_id: string; missed_amount: number }[]>('/evs/suspected-returns')
  if (!data?.length) return null
  const total = data.reduce((a, s) => a + (s.missed_amount || 0), 0)
  return (
    <Link
      to="/corrections"
      className="flex items-center gap-3 mb-4 px-4 py-3 rounded-xl border border-amber-300/70
                 bg-amber-50 text-amber-900 shadow-card hover:bg-amber-100/70 transition-colors"
    >
      <span className="pill bg-amber-200/80 text-amber-900">{data.length}</span>
      <span className="text-sm">
        <span className="font-semibold">Suspected EV return{data.length > 1 ? 's' : ''}</span>
        {' — '}rent worth ₹{moneyWhole(total)} kept accruing for EV
        {data.length > 1 ? 's' : ''} {data.slice(0, 4).map((s) => s.ev_id).join(', ')}
        {data.length > 4 ? '…' : ''} whose holders vanished from payouts. Review in Corrections →
      </span>
    </Link>
  )
}

export function DashboardPage() {
  // Default KPI window: the previous complete Mon–Sun week.
  const thisMon = startOfWeekISO(todayISO())
  const prevWeek = { from: addDaysISO(thisMon, -7), to: addDaysISO(thisMon, -1) }

  const [companies, setCompanies] = useUrlList('companies')
  const [dateFrom, setDateFrom] = useUrlString('from', prevWeek.from)
  const [dateTo, setDateTo] = useUrlString('to', prevWeek.to)
  const [tab, setTab] = useUrlString('tab', 'overview')
  const [weeksStr, setWeeks] = useUrlString('weeks', '12')
  const weeks = Math.max(1, Math.min(53, parseInt(weeksStr, 10) || 12))
  const [drawerMetric, setDrawerMetric] = useState<string | null>(null)

  const params = new URLSearchParams()
  if (companies.length) params.set('companies', companies.join(','))
  if (dateFrom) params.set('date_from', dateFrom)
  if (dateTo) params.set('date_to', dateTo)
  const {
    data,
    error,
    loading: busy,
  } = useApi<Summary>('/dashboard/summary' + (params.toString() ? '?' + params : ''))

  function setRangeDays(n: number) {
    setDateFrom(addDaysISO(todayISO(), -(n - 1)))
    setDateTo(todayISO())
  }
  function toggleCompany(c: string) {
    setCompanies((cs) => (cs.includes(c) ? cs.filter((x) => x !== c) : [...cs, c]))
  }

  if (busy && !data) return <Spinner label="Loading dashboard…" />
  if (error || !data) return <p className="text-red-600">{error ?? 'No data'}</p>
  const s = data.stats

  return (
    <div className="max-w-7xl mx-auto pb-12">
      {/* ── header + filters (one row above everything) ───────────── */}
      <div className="flex items-start justify-between flex-wrap gap-3 mb-4">
        <div>
          <h1 className="text-2xl font-bold">Dashboard</h1>
          <p className="text-slate-500 text-sm">
            Cards: <span className="font-medium">{data.window.from} → {data.window.to}</span>
            {' '}({data.window.days}d) · Trends: last {weeks} weeks ·{' '}
            {companies.length ? companies.join(', ') : 'all companies'}
          </p>
        </div>
        <div className="flex flex-col gap-2 items-end">
          <div className="flex flex-wrap gap-1.5 items-center justify-end">
            <span className="text-xs text-slate-500 mr-1">Companies:</span>
            <Chip active={companies.length === 0} onClick={() => setCompanies([])}>
              All
            </Chip>
            {data.filter.available_companies.map((c) => (
              <Chip key={c} active={companies.includes(c)} onClick={() => toggleCompany(c)}>
                {c}
              </Chip>
            ))}
          </div>
          <div className="flex flex-wrap gap-2 items-end justify-end">
            <label className="block text-sm">
              <span className="block text-xs text-slate-500">From</span>
              <input
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
                className="border rounded px-2 py-1 text-sm"
              />
            </label>
            <label className="block text-sm">
              <span className="block text-xs text-slate-500">To</span>
              <input
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                className="border rounded px-2 py-1 text-sm"
              />
            </label>
            <div className="flex gap-1 mb-0.5">
              <Chip
                active={dateFrom === prevWeek.from && dateTo === prevWeek.to}
                onClick={() => {
                  setDateFrom(prevWeek.from)
                  setDateTo(prevWeek.to)
                }}
              >
                Last wk
              </Chip>
              {(
                [
                  ['7d', 7],
                  ['30d', 30],
                  ['90d', 90],
                ] as const
              ).map(([label, n]) => (
                <Chip key={label} onClick={() => setRangeDays(n)}>
                  {label}
                </Chip>
              ))}
            </div>
            <label className="block text-sm">
              <span className="block text-xs text-slate-500">Weeks (trends)</span>
              <select
                value={String(weeks)}
                onChange={(e) => setWeeks(e.target.value)}
                className="border rounded px-2 py-1 text-sm"
              >
                {[8, 12, 26, 52].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>
      </div>

      <AttentionStrip />

      {/* ── KPI strip (always visible, clickable → drawer) ─────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-3 mb-4">
        <Kpi metric="payout" label="Released" value={moneyWhole(s.payout)} tone="blue"
             tip="Net cash released to riders during the window." onClick={setDrawerMetric} />
        <Kpi metric="rent_collected" label="Rent collected" value={moneyWhole(s.rent_collected)} tone="emerald"
             tip="Daily rent for every billed and recovered day in the window." onClick={setDrawerMetric} />
        <Kpi metric="rent_missed" label="Rent missed" value={moneyWhole(s.rent_missed)} tone="rose"
             tip="Rider was absent so rent fell to arrears this window. Click to see who." onClick={setDrawerMetric} />
        <Kpi metric="rent_pending" label="Rent pending" value={moneyWhole(s.rent_pending)} tone="amber"
             tip="Billable EV-days no cycle has processed yet — not lost, just not collected." onClick={setDrawerMetric} />
        <Kpi metric="arrears_recovered" label="Recovered" value={moneyWhole(s.arrears_recovered)} tone="emerald"
             tip="Old missed rent clawed back in this window." onClick={setDrawerMetric} />
        <Kpi metric="total_arrears" label="Arrears (live)" value={moneyWhole(s.total_arrears)} tone="rose"
             tip="Snapshot, not window-scoped: EV arrears + general dues right now." onClick={setDrawerMetric} />
        <Kpi metric="active_riders" label="Active riders" value={integer(s.active_riders)} tone="slate"
             tip="Riders with a payout in the window." onClick={setDrawerMetric} />
        <Kpi metric="active_evs" label="Active EVs" value={integer(s.active_evs)} tone="slate"
             tip="EVs that earned rent during the window." onClick={setDrawerMetric} />
      </div>

      {/* ── tab bar ────────────────────────────────────────────────── */}
      <div className="flex gap-1 border-b border-slate-200 mb-4" role="tablist">
        {TABS.map(([key, label]) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={
              'px-4 py-2 text-sm font-medium rounded-t-lg -mb-px border ' +
              (tab === key
                ? 'bg-white border-slate-200 border-b-white text-brand'
                : 'bg-transparent border-transparent text-slate-500 hover:text-slate-700 hover:bg-slate-100')
            }
          >
            {label}
          </button>
        ))}
      </div>

      {/* ── tab content ────────────────────────────────────────────── */}
      {tab === 'overview' && (
        <>
          <OverviewTab companies={companies} weeks={weeks} />
          <SecondaryMetrics s={s} lifetime={data.lifetime} onClick={setDrawerMetric} />
          <RecentCycles rows={data.recent_cycle_per_company} />
        </>
      )}
      {tab === 'rent' && (
        <>
          <RentTab companies={companies} weeks={weeks} />
          <p className="text-xs text-slate-500 mt-3">
            Person-level arrears live on the{' '}
            <Link to="/arrears" className="text-brand underline">
              Arrears page
            </Link>{' '}
            (dormant riders — EV returned, debt kept — are hidden there by default).
          </p>
        </>
      )}
      {tab === 'fleet' && <FleetTab dateFrom={dateFrom} dateTo={dateTo} />}
      {tab === 'riders' && <RidersTab companies={companies} weeks={weeks} />}

      {/* ── reports ────────────────────────────────────────────────── */}
      <ReportPanel
        availableCompanies={data.filter.available_companies}
        availableWeeks={data.filter.available_weeks}
        currentCompanies={companies}
        currentDateFrom={dateFrom}
        currentDateTo={dateTo}
      />

      {drawerMetric && (
        <BreakdownDrawer
          metric={drawerMetric}
          companies={companies}
          dateFrom={dateFrom}
          dateTo={dateTo}
          onClose={() => setDrawerMetric(null)}
        />
      )}
    </div>
  )
}

// ── building blocks ──────────────────────────────────────────────────────

function Chip({
  active,
  onClick,
  children,
}: {
  active?: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className={
        'text-xs px-2 py-1 rounded ' +
        (active ? 'bg-brand text-white' : 'bg-slate-200 hover:bg-slate-300')
      }
    >
      {children}
    </button>
  )
}

type Tone = 'emerald' | 'rose' | 'amber' | 'blue' | 'slate'
const TONE_BORDER: Record<Tone, string> = {
  emerald: 'border-l-4 border-emerald-500',
  rose: 'border-l-4 border-rose-500',
  amber: 'border-l-4 border-amber-500',
  blue: 'border-l-4 border-blue-500',
  slate: 'border-l-4 border-slate-400',
}

function Kpi({
  metric,
  label,
  value,
  tone,
  tip,
  onClick,
}: {
  metric?: string
  label: string
  value: string
  tone: Tone
  tip?: string
  onClick?: (metric: string) => void
}) {
  const interactive = metric && onClick
  return (
    <div
      role={interactive ? 'button' : undefined}
      tabIndex={interactive ? 0 : undefined}
      title={tip}
      onClick={interactive ? () => onClick(metric) : undefined}
      onKeyDown={
        interactive
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                onClick(metric)
              }
            }
          : undefined
      }
      className={`bg-white rounded-xl border border-slate-200/80 shadow-card p-3 ${TONE_BORDER[tone]} ${
        interactive ? 'cursor-pointer hover:-translate-y-0.5 hover:shadow-glass transition' : ''
      }`}
    >
      <p className="text-xs text-slate-500 truncate">{label}</p>
      <p className="text-lg font-bold mt-1">{value}</p>
    </div>
  )
}

function SecondaryMetrics({
  s,
  lifetime,
  onClick,
}: {
  s: Stats
  lifetime: { total_riders: number; total_evs: number; total_payout: number }
  onClick: (metric: string) => void
}) {
  const items: [string, string, string, string][] = [
    // [metric, label, value, tip]
    ['rent_expected', 'Rent expected', moneyWhole(s.rent_expected), 'Every billable EV-day at its daily rate.'],
    ['rent_partial', 'Partial rent', moneyWhole(s.rent_partial), 'Charged minus collected per rider — the shortfall that rolled to dues.'],
    ['manual_rent', 'Manual rent', moneyWhole(s.manual_rent), 'Manual rent payments logged in the window.'],
    ['hold', 'Held', moneyWhole(s.hold), 'Money held back from payouts (gross − released).'],
    ['cod', 'COD', moneyWhole(s.cod), 'COD held in the window.'],
    ['provider_owed', 'Owed to providers', moneyWhole(s.provider_owed), 'Daily provider cost across every EV with ledger rows.'],
    ['inactive_riders', 'Inactive riders', integer(s.inactive_riders), 'Active roster but no payout anywhere in the window.'],
    ['inactive_evs', 'Inactive EVs', integer(s.inactive_evs), 'EVs with at least one missed day in the window.'],
    ['untouched_evs', 'Untouched EVs', integer(s.untouched_evs), 'In-use EVs with no ledger activity in the window.'],
  ]
  return (
    <Panel
      title="More metrics"
      subtitle="same window as the cards — click any to see rows"
      className="mt-4"
    >
      <div className="grid grid-cols-3 md:grid-cols-5 lg:grid-cols-9 gap-2">
        {items.map(([metric, label, value, tip]) => (
          <button
            key={metric}
            title={tip}
            onClick={() => onClick(metric)}
            className="text-left rounded-lg border border-slate-200 px-2.5 py-2 hover:bg-slate-50 hover:border-slate-300 transition"
          >
            <p className="text-[11px] text-slate-500 truncate">{label}</p>
            <p className="text-sm font-semibold mt-0.5">{value}</p>
          </button>
        ))}
      </div>
      <p className="text-xs text-slate-400 mt-3">
        Lifetime: {integer(lifetime.total_riders)} riders · {integer(lifetime.total_evs)} EVs ·
        ₹{moneyWhole(lifetime.total_payout)} paid out all-time.
      </p>
    </Panel>
  )
}

function RecentCycles({ rows }: { rows: Summary['recent_cycle_per_company'] }) {
  return (
    <Panel
      title="Most recent cycle per company"
      subtitle="where each company is right now"
      className="mt-4"
    >
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-100 text-left">
            <tr>
              <th className="px-3 py-2 text-xs">Company</th>
              <th className="px-3 py-2 text-xs">Cycle</th>
              <th className="px-3 py-2 text-xs text-right">Riders</th>
              <th className="px-3 py-2 text-xs text-right">Released</th>
              <th className="px-3 py-2 text-xs text-right">Rent charged</th>
              <th className="px-3 py-2 text-xs text-right">Collected</th>
              <th className="px-3 py-2 text-xs text-right">Missed</th>
              <th className="px-3 py-2 text-xs">Processed</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={8} className="p-3 text-center text-slate-500 text-sm">
                  No cycle history yet. Process a payout to populate.
                </td>
              </tr>
            )}
            {rows.map((r) => (
              <tr key={r.company} className="border-t hover:bg-slate-50">
                <td className="px-3 py-2 font-medium">{r.company}</td>
                <td className="px-3 py-2 text-xs">
                  {r.cycle_start} → {r.cycle_end}
                </td>
                <td className="px-3 py-2 text-right">{integer(r.rider_count)}</td>
                <td className="px-3 py-2 text-right font-mono">{money(r.total_release)}</td>
                <td className="px-3 py-2 text-right font-mono">{money(r.total_rent_charged)}</td>
                <td className="px-3 py-2 text-right font-mono text-emerald-700">
                  {money(r.total_rent_collected)}
                </td>
                <td className="px-3 py-2 text-right font-mono text-rose-700">
                  {money(r.total_rent_missed)}
                </td>
                <td className="px-3 py-2 text-xs text-slate-500">{r.processed_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}

function BreakdownDrawer({
  metric,
  companies,
  dateFrom,
  dateTo,
  onClose,
}: {
  metric: string
  companies: string[]
  dateFrom: string
  dateTo: string
  onClose: () => void
}) {
  const params = new URLSearchParams()
  if (companies.length) params.set('companies', companies.join(','))
  if (dateFrom) params.set('date_from', dateFrom)
  if (dateTo) params.set('date_to', dateTo)
  const { data, loading: busy, error } = useApi<Breakdown>(
    '/dashboard/breakdown/' + metric + (params.toString() ? '?' + params : ''),
  )
  return (
    <div className="fixed inset-0 z-50 flex" onClick={onClose}>
      <div className="flex-1 bg-black/40" />
      <div
        className="bg-white w-full max-w-4xl shadow-2xl overflow-y-auto flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 py-3 border-b flex items-center justify-between sticky top-0 bg-white z-10">
          <div>
            <h3 className="font-semibold">{data?.title ?? metric}</h3>
            <p className="text-xs text-slate-500">
              {(dateFrom || dateTo) && (
                <>
                  {dateFrom} → {dateTo} ·{' '}
                </>
              )}
              {companies.length ? companies.join(', ') : 'all companies'}
            </p>
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-700">
            ✕
          </button>
        </div>
        <div className="flex-1 p-4">
          {busy && <Spinner />}
          {error && !busy && (
            <p role="alert" className="text-center text-rose-600 p-8">
              {error}
            </p>
          )}
          {data && !busy && !error && (
            data.rows.length === 0 ? (
              <p className="text-center text-slate-400 p-8">No rows.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-slate-100 text-left sticky top-0">
                    <tr>
                      {data.columns.map((c) => (
                        <th key={c} className="px-3 py-2 text-xs font-medium">
                          {c.replace(/_/g, ' ')}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.rows.map((r, i) => (
                      <tr key={i} className="border-t hover:bg-slate-50">
                        {data.columns.map((c) => (
                          <td key={c} className="px-3 py-2 text-xs">
                            {renderCell(c, r[c])}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          )}
        </div>
      </div>
    </div>
  )
}

function ReportPanel({
  availableCompanies,
  availableWeeks,
  currentCompanies,
  currentDateFrom,
  currentDateTo,
}: {
  availableCompanies: string[]
  availableWeeks: WeekOption[]
  currentCompanies: string[]
  currentDateFrom: string
  currentDateTo: string
}) {
  type Mode = 'current' | 'range' | 'specific'
  const [mode, setMode] = useState<Mode>('current')
  const [from, setFrom] = useState<string>('')
  const [to, setTo] = useState<string>('')
  const [cycleEnd, setCycleEnd] = useState<string>('')
  const [cycleCompany, setCycleCompany] = useState<string>('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function go() {
    setBusy(true)
    setErr(null)
    try {
      const params = new URLSearchParams({ mode })
      if (currentCompanies.length) params.set('companies', currentCompanies.join(','))
      if (mode === 'current') {
        if (currentDateFrom) params.set('from_date', currentDateFrom)
        if (currentDateTo) params.set('to_date', currentDateTo)
      }
      if (mode === 'range') {
        if (!from || !to) throw new Error('Pick both From and To dates.')
        params.set('from_date', from)
        params.set('to_date', to)
      }
      if (mode === 'specific') {
        if (!cycleEnd || !cycleCompany) throw new Error('Pick a cycle.')
        params.set('cycle_end', cycleEnd)
        params.set('cycle_company', cycleCompany)
      }
      saveBlob(
        await api.download('/dashboard/export?' + params, {
          fallbackName: `dashboard_${mode}.xlsx`,
        }),
      )
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Panel
      title="Reports"
      subtitle="multi-sheet styled .xlsx — same look as the cycle workbook"
      className="mt-4"
    >
      <div className="flex flex-wrap gap-3 items-end">
        <label className="text-sm">
          <span className="block text-xs text-slate-500">Scope</span>
          <select
            value={mode}
            onChange={(e) => setMode(e.target.value as Mode)}
            className="border rounded px-2 py-1 text-sm"
          >
            <option value="current">Current view (filter)</option>
            <option value="range">Custom date range</option>
            <option value="specific">Specific payout</option>
          </select>
        </label>
        {mode === 'range' && (
          <>
            <label className="text-sm">
              <span className="block text-xs text-slate-500">From</span>
              <input
                type="date"
                value={from}
                onChange={(e) => setFrom(e.target.value)}
                className="border rounded px-2 py-1 text-sm"
              />
            </label>
            <label className="text-sm">
              <span className="block text-xs text-slate-500">To</span>
              <input
                type="date"
                value={to}
                onChange={(e) => setTo(e.target.value)}
                className="border rounded px-2 py-1 text-sm"
              />
            </label>
          </>
        )}
        {mode === 'specific' && (
          <>
            <label className="text-sm">
              <span className="block text-xs text-slate-500">Company</span>
              <select
                value={cycleCompany}
                onChange={(e) => setCycleCompany(e.target.value)}
                className="border rounded px-2 py-1 text-sm"
              >
                <option value="">(pick one)</option>
                {availableCompanies.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm">
              <span className="block text-xs text-slate-500">Cycle end</span>
              <select
                value={cycleEnd}
                onChange={(e) => setCycleEnd(e.target.value)}
                className="border rounded px-2 py-1 text-sm min-w-[160px]"
              >
                <option value="">(pick one)</option>
                {availableWeeks.map((w) => (
                  <option key={w.latest_end} value={w.latest_end}>
                    {w.latest_end} ({w.week_bucket})
                  </option>
                ))}
              </select>
            </label>
          </>
        )}
        <button
          onClick={go}
          disabled={busy}
          className="text-sm bg-emerald-600 hover:bg-emerald-700 text-white px-3 py-1.5 rounded inline-flex items-center gap-1 disabled:opacity-50"
        >
          <span>⬇</span>
          {busy ? 'Generating…' : 'Download report'}
        </button>
        {err && <span className="text-xs text-red-600">{err}</span>}
      </div>
      <p className="text-xs text-slate-500 mt-3">
        Sheets included: Overview · <b>EV Rent vs Expected</b> · <b>Riders in Arrears</b> · Active
        EVs · Inactive EVs · Money Flow · Manual Rent Payments · COD · Cycle History. Current-view
        scope respects the company chips and date range above. Specific-payout scope ignores them
        and uses just the (company, cycle_end) you pick here.
      </p>
    </Panel>
  )
}

function renderCell(col: string, value: unknown): React.ReactNode {
  if (value === null || value === undefined) return <span className="text-slate-300">—</span>
  if (col === 'person_id' && typeof value === 'number') {
    return (
      <Link to={'/persons/' + value} className="text-brand underline">
        #{value}
      </Link>
    )
  }
  if (col === 'ev_id' && typeof value === 'string') {
    return (
      <Link to={'/evs/' + encodeURIComponent(value)} className="text-brand underline">
        {value}
      </Link>
    )
  }
  if (typeof value === 'number') {
    return <span className="font-mono">{money(value)}</span>
  }
  return String(value)
}
