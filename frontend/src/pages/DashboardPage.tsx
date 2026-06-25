/**
 * Dashboard — 13 cycle-scoped stat cards + 3 lifetime cards + 5 charts +
 * top-arrears list + per-company recent-cycle summary. Filter is keyed on
 * ISO week_bucket so the dashboard correctly aggregates across companies
 * whose cycles end on different weekdays. Cards are clickable: click any
 * card to open a side drawer showing the underlying rows.
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { Spinner } from '../components/Spinner'

// ── types ────────────────────────────────────────────────────────────────
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
    date_to:   string
    available_companies: string[]
    available_weeks: WeekOption[]   // back-compat only, unused
  }
  window: {
    from: string
    to:   string
    days: number
  }
  stats: Stats
  lifetime: { total_riders: number; total_evs: number; total_payout: number }
  charts: {
    top_arrears: { person_id: number; name: string; ev_arrears: number; dues: number; arrears_total: number }[]
    ev_status: { status: string; count: number }[]
    releases_by_cycle: { label: string; value: number }[]
    rent_collected_by_cycle: { label: string; value: number }[]
    arrears_movement: { cycle_end: string; recovered: number; added: number }[]
  }
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

const fmt = (n: number) =>
  n.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })
const fmtFull = (n: number) =>
  n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })

// ── page ────────────────────────────────────────────────────────────────
export function DashboardPage() {
  const [data, setData] = useState<Summary | null>(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // Local-date formatter (avoids the UTC off-by-one near midnight).
  const isoLocal = (d: Date) => {
    const y = d.getFullYear()
    const m = String(d.getMonth() + 1).padStart(2, '0')
    const day = String(d.getDate()).padStart(2, '0')
    return `${y}-${m}-${day}`
  }
  // Default window: the previous complete Mon-Sun week.
  // (Placeholder until this is pivoted onto the Raft bill period.)
  const prevWeek = (() => {
    const t = new Date()
    const sinceMon = (t.getDay() + 6) % 7          // Mon=0 ... Sun=6
    const thisMon = new Date(t); thisMon.setDate(t.getDate() - sinceMon)
    const prevMon = new Date(thisMon); prevMon.setDate(thisMon.getDate() - 7)
    const prevSun = new Date(prevMon); prevSun.setDate(prevMon.getDate() + 6)
    return { from: isoLocal(prevMon), to: isoLocal(prevSun) }
  })()
  const [companies, setCompanies] = useState<string[]>([])
  const [dateFrom, setDateFrom] = useState<string>(prevWeek.from)
  const [dateTo, setDateTo]     = useState<string>(prevWeek.to)
  const [drawerMetric, setDrawerMetric] = useState<string | null>(null)

  const reload = () => {
    setBusy(true); setError(null)
    const params = new URLSearchParams()
    if (companies.length) params.set('companies', companies.join(','))
    if (dateFrom) params.set('date_from', dateFrom)
    if (dateTo)   params.set('date_to',   dateTo)
    api.get<Summary>('/dashboard/summary' + (params.toString() ? '?' + params : ''))
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false))
  }
  useEffect(reload, [companies, dateFrom, dateTo])

  // Helpers for quick-range buttons.
  function setRangeDays(n: number) {
    const t = new Date()
    const f = new Date(); f.setDate(f.getDate() - (n - 1))
    setDateFrom(isoLocal(f))
    setDateTo(isoLocal(t))
  }
  function setPrevWeek() {
    setDateFrom(prevWeek.from)
    setDateTo(prevWeek.to)
  }

  function toggleCompany(c: string) {
    setCompanies((cs) => cs.includes(c) ? cs.filter((x) => x !== c) : [...cs, c])
  }

  if (busy && !data) return <Spinner label="Loading dashboard…" />
  if (error || !data) return <p className="text-red-600">{error ?? 'No data'}</p>

  return (
    <div className="max-w-7xl mx-auto pb-12">
      <div className="flex items-start justify-between flex-wrap gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold">Dashboard</h1>
          <p className="text-slate-500 text-sm">
            Window <span className="font-medium">{data.window.from} → {data.window.to}</span>
            {' '}({data.window.days} days) ·{' '}
            {companies.length ? companies.join(', ') : 'all companies'}
          </p>
        </div>
        <div className="flex flex-col gap-2 items-end">
          <div className="flex flex-wrap gap-1.5 items-end justify-end">
            <div className="text-xs text-slate-500 self-end mr-1">Companies:</div>
            <button
              onClick={() => setCompanies([])}
              className={'text-xs px-2 py-1 rounded ' +
                (companies.length === 0
                  ? 'bg-brand text-white'
                  : 'bg-slate-200 hover:bg-slate-300')}>
              All
            </button>
            {data.filter.available_companies.map((c) => (
              <button
                key={c}
                onClick={() => toggleCompany(c)}
                className={'text-xs px-2 py-1 rounded ' +
                  (companies.includes(c)
                    ? 'bg-brand text-white'
                    : 'bg-slate-200 hover:bg-slate-300')}>
                {c}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap gap-2 items-end">
            <label className="block text-sm">
              <span className="block text-xs text-slate-500">From</span>
              <input type="date" value={dateFrom}
                     onChange={(e) => setDateFrom(e.target.value)}
                     className="border rounded px-2 py-1 text-sm" />
            </label>
            <label className="block text-sm">
              <span className="block text-xs text-slate-500">To</span>
              <input type="date" value={dateTo}
                     onChange={(e) => setDateTo(e.target.value)}
                     className="border rounded px-2 py-1 text-sm" />
            </label>
            <div className="flex gap-1 mb-0.5">
              <button onClick={setPrevWeek}
                      className="text-xs px-2 py-1 rounded bg-slate-200 hover:bg-slate-300">
                Last wk
              </button>
              {[
                ['7d', 7], ['30d', 30], ['90d', 90],
              ].map(([label, n]) => (
                <button key={label as string}
                        onClick={() => setRangeDays(n as number)}
                        className="text-xs px-2 py-1 rounded bg-slate-200 hover:bg-slate-300">
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* ── Stat tiers (grouped for hierarchy) ───────────────────── */}
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-2 mt-1">Rent this period</p>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3 mb-5">
        <Card metric="rent_expected" label="Rent Expected" value={fmtFull(data.stats.rent_expected)}
              tone="slate" tip="Sum of daily rent we should have collected for the window — every billable EV-day at its daily rate."
              onClick={setDrawerMetric} />
        <Card metric="rent_collected" label="Rent Collected" value={fmtFull(data.stats.rent_collected)}
              tone="emerald" tip="Actually collected — daily rent for every 'billed' and 'recovered' day in the window."
              onClick={setDrawerMetric} />
        <Card metric="rent_missed" label="Rent Missed" value={fmtFull(data.stats.rent_missed)}
              tone="rose" tip="Rider was absent so rent fell to arrears this window — a real loss. Click to see who."
              onClick={setDrawerMetric} />
        <Card metric="rent_pending" label="Rent Pending" value={fmtFull(data.stats.rent_pending)}
              tone="amber" tip="Billable EV-days no cycle has processed yet — not lost, just not collected. Shrinks as cycles run."
              onClick={setDrawerMetric} />
        <Card metric="rent_partial" label="Partial Rent" value={fmtFull(data.stats.rent_partial)}
              tone="amber" tip="Rent charged this window minus rent collected in cash, per rider - the shortfall that rolled to dues. Click to see who underpaid."
              onClick={setDrawerMetric} />
        <Card metric="arrears_recovered" label="Arrears Recovered" value={fmtFull(data.stats.arrears_recovered)}
              tone="emerald" tip="Old missed rent clawed back in this window (RENT_RECOVERED + XC_RENT_RECOVERED)."
              onClick={setDrawerMetric} />
      </div>

      <p className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-2 mt-1">Needs attention</p>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-5">
        <Card metric="inactive_riders" label="Inactive Riders" value={fmt(data.stats.inactive_riders)}
              tone="rose" tip="Riders with an active rider_master row in scope but no PAYOUT anywhere they work during the window. Click to see who."
              onClick={setDrawerMetric} />
        <Card metric="total_arrears" label="Due Rent (arrears, live)" value={fmtFull(data.stats.total_arrears)}
              tone="rose" tip="Snapshot, not window-scoped: EV arrears outstanding + general dues across every rider right now."
              onClick={setDrawerMetric} />
        <Card metric="inactive_evs" label="Inactive EVs" value={fmt(data.stats.inactive_evs)}
              tone="rose" tip="EVs that had at least one 'missed' day in the window (rider absent)."
              onClick={setDrawerMetric} />
      </div>

      <p className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-2 mt-1">Fleet & activity</p>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3 mb-5">
        <Card metric="active_riders" label="Active Riders" value={fmt(data.stats.active_riders)}
              tone="slate" tip="Riders who had a PAYOUT in any of their (selected) companies during the window."
              onClick={setDrawerMetric} />
        <Card metric="active_evs" label="Active EVs" value={fmt(data.stats.active_evs)}
              tone="slate" tip="EVs that earned rent (billed or recovered days) during the window."
              onClick={setDrawerMetric} />
        <Card metric="untouched_evs" label="Untouched EVs" value={fmt(data.stats.untouched_evs)}
              tone="slate" tip="In_use EVs with NO ledger activity in the window (idle, in maintenance, or no cycle has covered them yet). Active + Inactive + Untouched = total in_use."
              onClick={setDrawerMetric} />
        <Card metric="provider_owed" label="Owed to Providers" value={fmtFull(data.stats.provider_owed)}
              tone="slate" tip="What we owe Raft / Blive / etc. for the window — daily provider cost across every EV that had ledger rows."
              onClick={setDrawerMetric} />
      </div>

      <p className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-2 mt-1">Money movement</p>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3 mb-5">
        <Card metric="payout" label="Payout" value={fmtFull(data.stats.payout)}
              tone="slate" tip="Net cash released to riders during the window."
              onClick={setDrawerMetric} />
        <Card metric="hold" label="HOLD" value={fmtFull(data.stats.hold)}
              tone="slate" tip="Money held back from rider payouts in the window (gross payout − net released)."
              onClick={setDrawerMetric} />
        <Card metric="cod" label="COD" value={fmtFull(data.stats.cod)}
              tone="slate" tip="COD held in the window."
              onClick={setDrawerMetric} />
        <Card metric="manual_rent" label="Rent Paid Manually" value={fmtFull(data.stats.manual_rent)}
              tone="slate" tip="Manual rent payments logged in the window (cash / UPI / off-bank)."
              onClick={setDrawerMetric} />
      </div>

      {/* ── Lifetime trio ───────────────────────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-6">
        <Card label="Total Riders" value={fmt(data.lifetime.total_riders)}
              tone="slate" tip="All persons in the registry, lifetime." big />
        <Card label="Total EVs" value={fmt(data.lifetime.total_evs)}
              tone="slate" tip="EV units, excluding returned ones." big />
        <Card label="Total Payout" value={fmtFull(data.lifetime.total_payout)}
              tone="slate" tip="Cash released to riders across every cycle ever." big />
      </div>

      {/* ── Charts grid ─────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
        <Panel title="EV Fleet Status" subtitle="Units by status (live)">
          <PieChart slices={data.charts.ev_status.map((s) => ({
            label: s.status, value: s.count,
          }))} />
        </Panel>
        <Panel title="Payout Released per Cycle" subtitle="Cycles ending in window — respects filters">
          <LineChart points={data.charts.releases_by_cycle} color="#1e40af" />
        </Panel>
        <Panel title="EV Rent Collected per Cycle" subtitle="Cycles ending in window — respects filters">
          <LineChart points={data.charts.rent_collected_by_cycle} color="#059669" />
        </Panel>
        <Panel title="Arrears Movement" subtitle="Recovered vs added — cycle_ends in window" wide>
          <ArrearsMovementChart points={data.charts.arrears_movement} />
        </Panel>
      </div>

      {/* ── All-arrears list (scrollable, replaces the old duplicate) ── */}
      <Panel title={`All riders with arrears or dues (${data.charts.top_arrears.length})`}
             subtitle="Sorted worst-first. Click a person to open the profile.">
        <div className="overflow-x-auto overflow-y-auto max-h-[480px] border rounded">
          <table className="w-full text-sm">
            <thead className="bg-slate-100 text-left sticky top-0 z-10">
              <tr>
                <th className="px-3 py-2 text-xs">#</th>
                <th className="px-3 py-2 text-xs">Person</th>
                <th className="px-3 py-2 text-xs">Name</th>
                <th className="px-3 py-2 text-xs text-right">EV Arrears</th>
                <th className="px-3 py-2 text-xs text-right">Dues</th>
                <th className="px-3 py-2 text-xs text-right">Total</th>
              </tr>
            </thead>
            <tbody>
              {data.charts.top_arrears.length === 0 && (
                <tr><td colSpan={6} className="p-6 text-center text-slate-500 text-sm">
                  No riders in arrears. Nice.
                </td></tr>
              )}
              {data.charts.top_arrears.map((r, i) => (
                <tr key={r.person_id} className="border-t hover:bg-slate-50">
                  <td className="px-3 py-2 text-xs text-slate-500">{i + 1}</td>
                  <td className="px-3 py-2">
                    <Link to={'/persons/' + r.person_id} className="text-brand underline">#{r.person_id}</Link>
                  </td>
                  <td className="px-3 py-2">{r.name}</td>
                  <td className="px-3 py-2 text-right text-amber-700">{fmtFull(r.ev_arrears)}</td>
                  <td className="px-3 py-2 text-right text-blue-700">{fmtFull(r.dues)}</td>
                  <td className="px-3 py-2 text-right font-bold text-red-700">{fmtFull(r.arrears_total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {/* ── Recent cycle per company ────────────────────────────────── */}
      <Panel title="Most recent cycle per company" subtitle="Where each company is right now"
             className="mt-4">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-100 text-left">
              <tr>
                <th className="px-3 py-2 text-xs">Company</th>
                <th className="px-3 py-2 text-xs">Cycle</th>
                <th className="px-3 py-2 text-xs">Week</th>
                <th className="px-3 py-2 text-xs text-right">Riders</th>
                <th className="px-3 py-2 text-xs text-right">Released</th>
                <th className="px-3 py-2 text-xs text-right">Rent charged</th>
                <th className="px-3 py-2 text-xs text-right">Collected</th>
                <th className="px-3 py-2 text-xs text-right">Missed</th>
                <th className="px-3 py-2 text-xs">Processed at</th>
              </tr>
            </thead>
            <tbody>
              {data.recent_cycle_per_company.length === 0 && (
                <tr><td colSpan={9} className="p-3 text-center text-slate-500 text-sm">
                  No cycle history yet. Process a payout to populate.
                </td></tr>
              )}
              {data.recent_cycle_per_company.map((r) => (
                <tr key={r.company} className="border-t hover:bg-slate-50">
                  <td className="px-3 py-2 font-medium">{r.company}</td>
                  <td className="px-3 py-2 text-xs">{r.cycle_start} → {r.cycle_end}</td>
                  <td className="px-3 py-2 text-xs text-slate-500">{r.week_bucket}</td>
                  <td className="px-3 py-2 text-right">{fmt(r.rider_count)}</td>
                  <td className="px-3 py-2 text-right text-blue-700">{fmtFull(r.total_release)}</td>
                  <td className="px-3 py-2 text-right">{fmtFull(r.total_rent_charged)}</td>
                  <td className="px-3 py-2 text-right text-emerald-700">{fmtFull(r.total_rent_collected)}</td>
                  <td className="px-3 py-2 text-right text-rose-700">{fmtFull(r.total_rent_missed)}</td>
                  <td className="px-3 py-2 text-xs text-slate-500">{r.processed_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {/* ── Reports ─────────────────────────────────────────────────── */}
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

// ── building blocks ─────────────────────────────────────────────────────
function Card({ metric, label, value, tone, tip, big, onClick }: {
  metric?: string
  label: string; value: string
  tone: 'emerald' | 'rose' | 'amber' | 'indigo' | 'purple' | 'blue' | 'slate'
  tip?: string
  big?: boolean
  onClick?: (metric: string) => void
}) {
  const borderClass = {
    emerald: 'border-l-4 border-emerald-500',
    rose:    'border-l-4 border-rose-500',
    amber:   'border-l-4 border-amber-500',
    indigo:  'border-l-4 border-indigo-500',
    purple:  'border-l-4 border-purple-500',
    blue:    'border-l-4 border-blue-500',
    slate:   'border-l-4 border-slate-500',
  }[tone]
  const interactive = metric && onClick
  return (
    <div
      role={interactive ? 'button' : undefined}
      tabIndex={interactive ? 0 : undefined}
      title={tip}
      onClick={interactive ? () => onClick(metric) : undefined}
      onKeyDown={interactive ? (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(metric) }
      } : undefined}
      className={`bg-white/80 backdrop-blur-xl rounded-xl shadow-card transition-shadow duration-200 hover:shadow-glass p-3 ${borderClass} ${interactive ? 'cursor-pointer hover:-translate-y-0.5 transition' : ''}`}
    >
      <p className="text-xs text-slate-500 flex items-center gap-1">
        {label}
        {tip && <span className="text-slate-300 cursor-help">ⓘ</span>}
        {interactive && <span className="ml-auto text-slate-300 text-[10px]">click ▸</span>}
      </p>
      <p className={(big ? 'text-2xl' : 'text-lg') + ' font-bold mt-1'}>{value}</p>
    </div>
  )
}

function Panel({ title, subtitle, children, wide, className = '' }: {
  title: string; subtitle?: string
  children: React.ReactNode
  wide?: boolean
  className?: string
}) {
  return (
    <div className={`bg-white/80 backdrop-blur-xl rounded-xl shadow-card transition-shadow duration-200 hover:shadow-glass p-4 ${wide ? 'lg:col-span-2' : ''} ${className}`}>
      <div className="flex items-baseline justify-between mb-2">
        <h3 className="font-semibold">{title}</h3>
        {subtitle && <span className="text-xs text-slate-400">{subtitle}</span>}
      </div>
      {children}
    </div>
  )
}

function BreakdownDrawer({ metric, companies, dateFrom, dateTo, onClose }: {
  metric: string
  companies: string[]
  dateFrom: string
  dateTo:   string
  onClose: () => void
}) {
  const [data, setData] = useState<Breakdown | null>(null)
  const [busy, setBusy] = useState(true)
  useEffect(() => {
    setBusy(true)
    const params = new URLSearchParams()
    if (companies.length) params.set('companies', companies.join(','))
    if (dateFrom) params.set('date_from', dateFrom)
    if (dateTo)   params.set('date_to',   dateTo)
    api.get<Breakdown>('/dashboard/breakdown/' + metric +
                       (params.toString() ? '?' + params : ''))
      .then(setData).finally(() => setBusy(false))
  }, [metric, companies, dateFrom, dateTo])
  return (
    <div className="fixed inset-0 z-50 flex" onClick={onClose}>
      <div className="flex-1 bg-black/40" />
      <div className="bg-white w-full max-w-4xl shadow-2xl overflow-y-auto flex flex-col"
           onClick={(e) => e.stopPropagation()}>
        <div className="px-5 py-3 border-b flex items-center justify-between sticky top-0 bg-white z-10">
          <div>
            <h3 className="font-semibold">{data?.title ?? metric}</h3>
            <p className="text-xs text-slate-500">
              {(dateFrom || dateTo) && <>{dateFrom} → {dateTo} · </>}
              {companies.length ? companies.join(', ') : 'all companies'}
            </p>
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-700">✕</button>
        </div>
        <div className="flex-1 p-4">
          {busy && <Spinner />}
          {data && !busy && (
            data.rows.length === 0
              ? <p className="text-center text-slate-400 p-8">No rows.</p>
              : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-slate-100 text-left sticky top-0">
                      <tr>
                        {data.columns.map((c) =>
                          <th key={c} className="px-3 py-2 text-xs font-medium">
                            {c.replace(/_/g, ' ')}
                          </th>
                        )}
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
  availableCompanies, availableWeeks, currentCompanies, currentDateFrom, currentDateTo,
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
    setBusy(true); setErr(null)
    try {
      const params = new URLSearchParams({ mode })
      if (currentCompanies.length) params.set('companies', currentCompanies.join(','))
      if (mode === 'current') {
        if (currentDateFrom) params.set('from_date', currentDateFrom)
        if (currentDateTo)   params.set('to_date',   currentDateTo)
      }
      if (mode === 'range') {
        if (!from || !to) throw new Error('Pick both From and To dates.')
        params.set('from_date', from); params.set('to_date', to)
      }
      if (mode === 'specific') {
        if (!cycleEnd || !cycleCompany) throw new Error('Pick a cycle.')
        params.set('cycle_end', cycleEnd); params.set('cycle_company', cycleCompany)
      }
      const r = await fetch('/api/dashboard/export?' + params, {
        credentials: 'include',
      })
      if (!r.ok) {
        const t = await r.text()
        throw new Error('Export failed: ' + (t || r.statusText))
      }
      let name = `dashboard_${mode}.xlsx`
      const cd = r.headers.get('content-disposition') ?? ''
      const m = cd.match(/filename="?([^"]+)"?/i)
      if (m) name = m[1]
      const blob = await r.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = name
      document.body.appendChild(a); a.click(); a.remove()
      URL.revokeObjectURL(url)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Panel title="Reports" subtitle="Multi-sheet styled .xlsx — same look as the cycle workbook"
           className="mt-4">
      <div className="flex flex-wrap gap-3 items-end">
        <label className="text-sm">
          <span className="block text-xs text-slate-500">Scope</span>
          <select value={mode} onChange={(e) => setMode(e.target.value as Mode)}
                  className="border rounded px-2 py-1 text-sm">
            <option value="current">Current view (filter)</option>
            <option value="range">Custom date range</option>
            <option value="specific">Specific payout</option>
          </select>
        </label>
        {mode === 'range' && (
          <>
            <label className="text-sm">
              <span className="block text-xs text-slate-500">From</span>
              <input type="date" value={from} onChange={(e) => setFrom(e.target.value)}
                     className="border rounded px-2 py-1 text-sm" />
            </label>
            <label className="text-sm">
              <span className="block text-xs text-slate-500">To</span>
              <input type="date" value={to} onChange={(e) => setTo(e.target.value)}
                     className="border rounded px-2 py-1 text-sm" />
            </label>
          </>
        )}
        {mode === 'specific' && (
          <>
            <label className="text-sm">
              <span className="block text-xs text-slate-500">Company</span>
              <select value={cycleCompany} onChange={(e) => setCycleCompany(e.target.value)}
                      className="border rounded px-2 py-1 text-sm">
                <option value="">(pick one)</option>
                {availableCompanies.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </label>
            <label className="text-sm">
              <span className="block text-xs text-slate-500">Cycle end</span>
              <select value={cycleEnd} onChange={(e) => setCycleEnd(e.target.value)}
                      className="border rounded px-2 py-1 text-sm min-w-[160px]">
                <option value="">(pick one)</option>
                {availableWeeks.map((w) =>
                  <option key={w.latest_end} value={w.latest_end}>
                    {w.latest_end} ({w.week_bucket})
                  </option>)}
              </select>
            </label>
          </>
        )}
        <button onClick={go} disabled={busy}
                className="text-sm bg-emerald-600 hover:bg-emerald-700 text-white px-3 py-1.5 rounded inline-flex items-center gap-1 disabled:opacity-50">
          <span>⬇</span>
          {busy ? 'Generating…' : 'Download report'}
        </button>
        {err && <span className="text-xs text-red-600">{err}</span>}
      </div>
      <p className="text-xs text-slate-500 mt-3">
        Sheets included: Overview · <b>EV Rent vs Expected</b> · <b>Riders in Arrears</b> ·
        Active EVs · Inactive EVs · Money Flow · Manual Rent Payments · COD · Cycle History.
        Current-view scope respects the company chips and week dropdown above. Specific-payout
        scope ignores them and uses just the (company, cycle_end) you pick here.
      </p>
    </Panel>
  )
}

function renderCell(col: string, value: unknown): React.ReactNode {
  if (value === null || value === undefined) return <span className="text-slate-300">—</span>
  if (col === 'person_id' && typeof value === 'number') {
    return <Link to={'/persons/' + value} className="text-brand underline">#{value}</Link>
  }
  if (col === 'ev_id' && typeof value === 'string') {
    return <Link to={'/evs/' + encodeURIComponent(value)} className="text-brand underline">{value}</Link>
  }
  if (typeof value === 'number') {
    return <span className="font-mono">{fmtFull(value)}</span>
  }
  return String(value)
}

// ── charts ──────────────────────────────────────────────────────────────

function PieChart({ slices }: { slices: { label: string; value: number }[] }) {
  const total = slices.reduce((a, s) => a + s.value, 0)
  if (total === 0) return <p className="text-slate-400 text-sm p-4 text-center">No EVs.</p>
  const colors = ['#10b981', '#f59e0b', '#3b82f6', '#ef4444', '#8b5cf6', '#94a3b8']
  let acc = 0
  const radius = 70
  const cx = 90, cy = 90
  return (
    <div className="flex gap-4 items-center flex-wrap">
      <svg width={180} height={180} viewBox="0 0 180 180">
        {slices.map((s, i) => {
          if (s.value === 0) return null
          const start = (acc / total) * 2 * Math.PI
          acc += s.value
          const end = (acc / total) * 2 * Math.PI
          const x1 = cx + radius * Math.sin(start)
          const y1 = cy - radius * Math.cos(start)
          const x2 = cx + radius * Math.sin(end)
          const y2 = cy - radius * Math.cos(end)
          const large = end - start > Math.PI ? 1 : 0
          const d = `M ${cx} ${cy} L ${x1} ${y1} A ${radius} ${radius} 0 ${large} 1 ${x2} ${y2} Z`
          return <path key={i} d={d} fill={colors[i % colors.length]} stroke="#fff" strokeWidth="1" />
        })}
      </svg>
      <div className="text-xs space-y-1">
        {slices.map((s, i) => (
          <div key={i} className="flex items-center gap-2">
            <span className="w-3 h-3 rounded" style={{ background: colors[i % colors.length] }} />
            <span className="capitalize">{s.label.replace('_', ' ')}</span>
            <span className="text-slate-500 ml-2">{s.value} · {((s.value / total) * 100).toFixed(1)}%</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function LineChart({ points, color }: { points: { label: string; value: number }[]; color: string }) {
  if (points.length === 0) return <p className="text-slate-400 text-sm p-4 text-center">No cycles yet.</p>
  const max = Math.max(...points.map((p) => p.value), 1)
  const W = 600, H = 180, P = 30
  const innerW = W - P * 2, innerH = H - P * 2
  const xStep = points.length > 1 ? innerW / (points.length - 1) : 0
  const xy = (i: number, v: number): [number, number] => [
    P + i * xStep, P + innerH - (v / max) * innerH,
  ]
  const path = points.map((p, i) => {
    const [x, y] = xy(i, p.value)
    return (i === 0 ? 'M' : 'L') + ` ${x} ${y}`
  }).join(' ')
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-44">
      {[0, 0.25, 0.5, 0.75, 1].map((f) => {
        const y = P + innerH - f * innerH
        return (
          <g key={f}>
            <line x1={P} y1={y} x2={W - P} y2={y} stroke="#e5e7eb" strokeWidth="1" />
            <text x={P - 4} y={y + 3} textAnchor="end" fontSize="9" fill="#64748b">
              {fmt(max * f)}
            </text>
          </g>
        )
      })}
      <path d={path} stroke={color} fill="none" strokeWidth="2" />
      {points.map((p, i) => {
        const [x, y] = xy(i, p.value)
        return (
          <circle key={i} cx={x} cy={y} r="3" fill={color}>
            <title>{p.label}: {fmtFull(p.value)}</title>
          </circle>
        )
      })}
    </svg>
  )
}

function ArrearsMovementChart({ points }: {
  points: { cycle_end: string; recovered: number; added: number }[]
}) {
  if (points.length === 0) return <p className="text-slate-400 text-sm p-4 text-center">No data yet.</p>
  const max = Math.max(...points.map((p) => Math.max(p.recovered, p.added)), 1)
  const W = 800, H = 200, P = 30
  const innerW = W - P * 2, innerH = H - P * 2
  const groupW = innerW / points.length
  const barW = groupW * 0.4
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-52">
        {[0, 0.25, 0.5, 0.75, 1].map((f) => {
          const y = P + innerH - f * innerH
          return (
            <g key={f}>
              <line x1={P} y1={y} x2={W - P} y2={y} stroke="#e5e7eb" />
              <text x={P - 4} y={y + 3} textAnchor="end" fontSize="9" fill="#64748b">
                {fmt(max * f)}
              </text>
            </g>
          )
        })}
        {points.map((p, i) => {
          const cx = P + groupW * i + groupW / 2
          const recH = (p.recovered / max) * innerH
          const addH = (p.added / max) * innerH
          return (
            <g key={i}>
              <rect x={cx - barW} y={P + innerH - recH} width={barW * 0.9}
                    height={recH} fill="#10b981">
                <title>Recovered: {fmtFull(p.recovered)}</title>
              </rect>
              <rect x={cx + barW * 0.05} y={P + innerH - addH} width={barW * 0.9}
                    height={addH} fill="#f43f5e">
                <title>Newly missed: {fmtFull(p.added)}</title>
              </rect>
              <text x={cx} y={H - 8} textAnchor="middle" fontSize="9" fill="#64748b">
                {p.cycle_end.slice(5)}
              </text>
            </g>
          )
        })}
      </svg>
      <div className="flex gap-3 text-xs justify-center">
        <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 bg-emerald-500" /> Recovered</span>
        <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 bg-rose-500" /> Newly missed</span>
      </div>
    </div>
  )
}
