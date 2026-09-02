/**
 * Dashboard, third generation — the money story, numbers first.
 *
 * A statistician's summary written for a layman: what came in, what we kept
 * and why, what went out; what rent was charged, how much was collected on
 * the spot, how much was missed, and what later happened to the missed part
 * (clawed back · written off because the EV was returned · still owed).
 * Charts are deliberately secondary — two compact weekly trends at the
 * bottom of the Story tab.
 *
 * Tabs: Story · Companies · EVs · Riders — the same numbers grouped by who
 * / what / where, as sortable tables with inline proportion bars.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useUrlList, useUrlString } from '../state/useUrlState'
import { useApi } from '../hooks/useApi'
import { Spinner } from '../components/Spinner'
import { moneyWhole } from '../lib/format'
import { addDaysISO, startOfWeekISO, todayISO } from '../lib/dates'
import { Link } from 'react-router-dom'
import { SortableTh, useSort } from '../components/Sortable'
import { C, LineChart } from './dashboard/charts'

// ── API shapes (rupees at the edge) ──────────────────────────────────────
interface Flow {
  gross_payout: number
  released: number
  rent_charged: number
  rent_collected: number
  rent_missed: number
  arrears_recovered: number
  written_off: number
  deposit_applied: number
  credit_offset: number
  refunded: number
  cod_held: number
}
interface Position {
  ev_arrears: number
  ev_arrears_active: number
  ev_arrears_dormant: number
  dormant_riders: number
  dues: number
  credit: number
  cod_uncleared: number
}
interface Story {
  window: { from: string; to: string; days: number }
  flow: Flow
  position: Position
}
interface TrendWeek {
  week: string
  week_start: string
  gross_payout: number
  released: number
  rent_charged: number
  rent_collected: number
  rent_missed: number
  arrears_recovered: number
}
interface AgingBucket {
  bucket: string
  riders: number
  outstanding: number
}
interface CompanyRow {
  company: string
  riders: number
  gross_payout: number
  released: number
  rent_charged: number
  rent_collected: number
  rent_missed: number
  arrears_recovered: number
  written_off: number
  outstanding: number
  dues: number
}
interface RiderRow {
  person_id: number
  display_name: string
  company: string | null
  gross_payout: number
  released: number
  rent_charged: number
  rent_collected: number
  rent_missed: number
  arrears_recovered: number
  written_off: number
  outstanding: number
  balance: number
}
interface EvRow {
  ev_id: string
  provider: string | null
  model: string | null
  status: string
  charged: number
  collected: number
  missed: number
  written_off: number
  provider_cost: number
  margin: number
  ledger_days: number
  holder: string | null
  holder_person_id: number | null
}

const TABS = [
  ['story', 'Story'],
  ['companies', 'Companies'],
  ['evs', 'EVs'],
  ['riders', 'Riders'],
] as const

// ── tiny building blocks (numbers first) ─────────────────────────────────

const r0 = (n: number | null | undefined) => '₹' + moneyWhole(n ?? 0)
const pct = (part: number, whole: number) =>
  whole > 0 ? Math.round((part / whole) * 100) : 0

function Big({ label, value, sub, tone, onClick }: {
  label: string
  value: string
  sub?: React.ReactNode
  tone?: 'good' | 'bad' | 'plain'
  onClick?: () => void
}) {
  return (
    <div
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onClick={onClick}
      onKeyDown={onClick ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick() } } : undefined}
      className={'panel p-4 flex-1 min-w-[180px] ' +
        (onClick ? 'cursor-pointer transition hover:-translate-y-0.5 hover:shadow-pop group/big' : '')}
    >
      <p className="text-xs text-slate-500 flex items-center justify-between">
        {label}
        {onClick && (
          <span className="text-slate-400 opacity-0 group-hover/big:opacity-100 transition-opacity">→</span>
        )}
      </p>
      <p className={'text-2xl font-bold font-display mt-1 tracking-tight ' +
        (tone === 'good' ? 'text-emerald-300' : tone === 'bad' ? 'text-red-300' : 'text-slate-900')}>
        {value}
      </p>
      {sub && <div className="text-xs text-slate-500 mt-1.5 leading-5">{sub}</div>}
    </div>
  )
}

/** A one-line proportion bar (chart second — it sits UNDER the numbers). */
function Ratio({ parts }: { parts: { value: number; color: string; label: string }[] }) {
  const total = parts.reduce((a, p) => a + p.value, 0)
  if (total <= 0) return null
  return (
    <div className="flex h-1.5 rounded-full overflow-hidden bg-white/[0.05] mt-2.5">
      {parts.map((p) => (
        <div
          key={p.label}
          title={`${p.label}: ${r0(p.value)}`}
          style={{ width: `${(p.value / total) * 100}%`, background: p.color }}
        />
      ))}
    </div>
  )
}

function MicroBar({ frac, color = C.aqua }: { frac: number; color?: string }) {
  return (
    <div className="w-14 h-1 rounded-full bg-white/[0.06] inline-block align-middle ml-2">
      <div className="h-1 rounded-full" style={{ width: `${Math.min(100, Math.max(0, frac * 100))}%`, background: color }} />
    </div>
  )
}

function Chip({ active, onClick, children }: {
  active: boolean; onClick: () => void; children: React.ReactNode
}) {
  return (
    <button onClick={onClick}
      className={'px-2.5 py-1 rounded-lg text-xs font-medium transition-colors ' +
        (active
          ? 'bg-brand-500/25 text-white shadow-[0_0_0_1px_rgba(139,92,246,0.4)]'
          : 'bg-white/[0.04] text-slate-500 hover:text-slate-800 hover:bg-white/[0.07]')}>
      {children}
    </button>
  )
}

interface BreakdownPayload {
  metric: string
  title: string
  columns: string[]
  rows: Record<string, unknown>[]
}

const _PLAIN_COLS = new Set([
  'person_id', 'rider_id', 'company', 'name', 'cycle_end', 'cycle_start',
  'created_at', 'order_number', 'txn_status', 'ev_id', 'days', 'riders',
])

function cellValue(col: string, v: unknown, i: number) {
  if (col === 'person_id' && typeof v === 'number') {
    return <Link key={i} to={'/persons/' + v} className="text-brand-300 hover:underline">#{v}</Link>
  }
  if (typeof v === 'number' && !_PLAIN_COLS.has(col)) return '₹' + moneyWhole(v)
  return String(v ?? '—')
}

const _DRILL_PAGE: Record<string, { to: string; label: string }> = {
  total_arrears: { to: '/arrears', label: 'Open the full Arrears page' },
  cod_uncleared: { to: '/cod', label: 'Open the COD page' },
  payout: { to: '/payments', label: 'Open Payments' },
  rent_collected: { to: '/ev-rent', label: 'Open the Rent Ledger' },
  credit_balances: { to: '/riders', label: 'Open Riders' },
}

/** Click a card → the rows behind the number, in a right-hand sheet. */
function BreakdownDrawer({ metric, suffix, onClose }: {
  metric: string
  suffix: string
  onClose: () => void
}) {
  const { data, loading, error } = useApi<BreakdownPayload>(
    `/dashboard/breakdown/${metric}${suffix}`,
  )
  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true"
         onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="flex-1 bg-black/60 backdrop-blur-[2px]" onMouseDown={onClose} />
      <div className="w-full max-w-2xl h-full overflow-y-auto panel-pop !rounded-none
                      border-l border-edge-strong animate-fade-up p-5">
        <div className="flex items-start justify-between gap-3 mb-3">
          <div>
            <h2 className="font-display font-semibold text-slate-900">
              {data?.title ?? 'Loading…'}
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              {data ? `${data.rows.length} row${data.rows.length === 1 ? '' : 's'}` : ''}
            </p>
          </div>
          <button onClick={onClose} className="btn-ghost !px-2.5" aria-label="Close">✕</button>
        </div>
        {loading && !data && <SkeletonTable cols={4} />}
        {error && <p className="text-red-400 text-sm">{error}</p>}
        {data && data.rows.length === 0 && (
          <p className="text-sm text-slate-500 py-8 text-center">Nothing behind this number.</p>
        )}
        {_DRILL_PAGE[metric] && (
          <Link to={_DRILL_PAGE[metric].to}
                className="inline-flex items-center gap-1.5 mb-3 text-sm text-brand-300 hover:underline">
            {_DRILL_PAGE[metric].label} →
          </Link>
        )}
        {data && data.rows.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left border-b border-edge-soft">
                <tr>
                  {data.columns.map((c) => (
                    <th key={c} className="px-2.5 py-2 whitespace-nowrap">{c.replace(/_/g, ' ')}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r, i) => (
                  <tr key={i} className="border-t border-edge-soft hover:bg-white/[0.02]">
                    {data.columns.map((c) => (
                      <td key={c} className={'px-2.5 py-1.5 whitespace-nowrap ' +
                        (typeof r[c] === 'number' && !_PLAIN_COLS.has(c) ? 'text-right tabular-nums' : '')}>
                        {cellValue(c, r[c], i)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

// ── the page ─────────────────────────────────────────────────────────────

/** Suspected EV returns — the fix that recovers money by closing EVs. */
function AttentionStrip() {
  const { data } = useApi<{ ev_id: string; missed_amount: number }[]>('/evs/suspected-returns')
  if (!data?.length) return null
  const total = data.reduce((a, s) => a + (s.missed_amount || 0), 0)
  return (
    <Link
      to="/corrections"
      className="flex items-center gap-3 mb-4 px-4 py-3 rounded-xl border border-amber-400/30
                 bg-amber-500/10 text-amber-200 shadow-card hover:bg-amber-500/15 transition-colors"
    >
      <span className="pill bg-amber-400/20 text-amber-200">{data.length}</span>
      <span className="text-sm">
        <span className="font-semibold">Suspected EV return{data.length > 1 ? 's' : ''}</span>
        {' — '}₹{moneyWhole(total)} of rent is accruing for {data.slice(0, 4).map((s) => s.ev_id).join(', ')}
        {data.length > 4 ? '…' : ''} whose holders vanished. Confirm the return and the charges reverse. →
      </span>
    </Link>
  )
}

export function DashboardPage() {
  const thisMon = startOfWeekISO(todayISO())
  const prevWeek = { from: addDaysISO(thisMon, -7), to: addDaysISO(thisMon, -1) }

  const [companies, setCompanies] = useUrlList('companies')
  const [dateFrom, setDateFrom] = useUrlString('from', prevWeek.from)
  const [dateTo, setDateTo] = useUrlString('to', prevWeek.to)
  const [tab, setTab] = useUrlString('tab', 'story')

  const qs = new URLSearchParams()
  if (companies.length) qs.set('companies', companies.join(','))
  if (dateFrom) qs.set('date_from', dateFrom)
  if (dateTo) qs.set('date_to', dateTo)
  const suffix = qs.toString() ? '?' + qs.toString() : ''

  const story = useApi<Story>('/dashboard/story' + suffix)
  const allCompanies = useApi<{ company_name: string }[]>('/companies')

  function setRangeDays(n: number) {
    setDateFrom(addDaysISO(todayISO(), -(n - 1)))
    setDateTo(todayISO())
  }
  const toggleCompany = (c: string) =>
    setCompanies((cs) => (cs.includes(c) ? cs.filter((x) => x !== c) : [...cs, c]))

  if (story.loading && !story.data) return <Spinner label="Reading the books…" />
  if (story.error || !story.data) return <p className="text-red-400">{story.error ?? 'No data'}</p>
  const s = story.data

  return (
    <div className="max-w-7xl mx-auto pb-12">
      <div className="flex items-start justify-between flex-wrap gap-3 mb-4">
        <div>
          <h1 className="page-title">Dashboard</h1>
          <p className="text-slate-500 text-sm mt-0.5">
            {s.window.from} → {s.window.to} ({s.window.days} days) ·{' '}
            {companies.length ? companies.join(', ') : 'all companies'}
          </p>
        </div>
        <div className="flex flex-col gap-2 items-end">
          <div className="flex flex-wrap gap-1.5 items-center justify-end">
            <Chip active={companies.length === 0} onClick={() => setCompanies([])}>All</Chip>
            {(allCompanies.data ?? []).map((c) => (
              <Chip key={c.company_name} active={companies.includes(c.company_name)}
                    onClick={() => toggleCompany(c.company_name)}>
                {c.company_name}
              </Chip>
            ))}
          </div>
          <div className="flex flex-wrap gap-2 items-end justify-end">
            <label className="block text-sm">
              <span className="block text-xs text-slate-500">From</span>
              <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
                     className="border rounded px-2 py-1 text-sm" />
            </label>
            <label className="block text-sm">
              <span className="block text-xs text-slate-500">To</span>
              <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
                     className="border rounded px-2 py-1 text-sm" />
            </label>
            <div className="flex gap-1 mb-0.5">
              <Chip active={dateFrom === prevWeek.from && dateTo === prevWeek.to}
                    onClick={() => { setDateFrom(prevWeek.from); setDateTo(prevWeek.to) }}>
                Last wk
              </Chip>
              {([7, 30, 90] as const).map((n) => (
                <Chip key={n} active={false} onClick={() => setRangeDays(n)}>{n}d</Chip>
              ))}
            </div>
          </div>
        </div>
      </div>

      <AttentionStrip />

      <div className="flex gap-1 border-b border-edge-soft mb-5" role="tablist">
        {TABS.map(([key, label]) => (
          <button key={key} role="tab" aria-selected={tab === key} onClick={() => setTab(key)}
            className={'relative px-4 py-2 text-sm font-medium -mb-px transition-colors ' +
              (tab === key
                ? 'text-slate-900 after:absolute after:left-2 after:right-2 after:-bottom-px after:h-[2px] ' +
                  'after:rounded-full after:bg-brand-400 after:shadow-[0_0_8px_rgba(139,92,246,0.7)]'
                : 'text-slate-500 hover:text-slate-800 hover:bg-white/[0.03] rounded-t-lg')}>
            {label}
          </button>
        ))}
      </div>

      {tab === 'story' && <StoryTab s={s} suffix={suffix} setTab={setTab} />}
      {tab === 'companies' && <CompaniesTab suffix={suffix} />}
      {tab === 'evs' && <EvsTab suffix={suffix} />}
      {tab === 'riders' && <RidersTab suffix={suffix} />}
    </div>
  )
}

// ── Story ────────────────────────────────────────────────────────────────

function StoryTab({ s, suffix, setTab }: {
  s: Story
  suffix: string
  setTab: (t: string) => void
}) {
  const navigate = useNavigate()
  const [drill, setDrill] = useState<string | null>(null)
  const f = s.flow
  const p = s.position
  const kept = Math.max(0, f.gross_payout - f.released)
  const chargedTotal = f.rent_charged + f.rent_missed
  const stillOwedDelta =
    f.rent_missed - f.written_off - f.arrears_recovered - f.deposit_applied

  return (
    <>
      {/* 1 · money in → held back → money out */}
      <div className="flex flex-wrap items-stretch gap-3 mb-5">
        <Big label="Came in from companies" value={r0(f.gross_payout)}
             sub={<>gross payouts for {`${s.window.days}`} days</>}
             onClick={() => setTab('companies')} />
        <div className="self-center text-slate-400 text-lg px-1 hidden md:block">→</div>
        <Big label="We held back" value={r0(kept)} onClick={() => setDrill('rent_collected')} sub={
          <>
            rent {r0(f.rent_collected)} · old debt {r0(f.arrears_recovered)}
            {f.cod_held > 0 && <> · COD {r0(f.cod_held)}</>}
          </>
        } />
        <div className="self-center text-slate-400 text-lg px-1 hidden md:block">→</div>
        <Big label="Paid out to riders" value={r0(f.released)} tone="good"
             sub={<>{pct(f.released, f.gross_payout)}% of what came in</>}
             onClick={() => setDrill('payout')} />
      </div>

      {/* 2 · the rent story */}
      <div className="panel p-5 mb-5">
        <h2 className="font-display font-semibold text-slate-900 mb-1">
          The rent story <span className="text-slate-500 font-sans text-sm font-normal">— this window</span>
        </h2>
        <p className="text-sm text-slate-500 mb-4">
          Of every ₹100 of rent billed, <span className="text-emerald-300 font-semibold">
          ₹{pct(f.rent_collected, chargedTotal)}</span> was collected on the spot and{' '}
          <span className="text-red-300 font-semibold">₹{pct(f.rent_missed, chargedTotal)}</span> became debt.
        </p>
        <div className="grid md:grid-cols-2 gap-x-10 gap-y-5">
          <div>
            <p className="text-sm text-slate-500">Rent we billed riders</p>
            <p className="text-3xl font-bold font-display text-slate-900 mt-0.5">{r0(chargedTotal)}</p>
            <div className="mt-3 space-y-1.5 text-sm">
              <p className="flex justify-between gap-4">
                <span className="text-slate-600">
                  <span className="inline-block w-2 h-2 rounded-full mr-2" style={{ background: C.aqua }} />
                  Collected on the spot
                </span>
                <span className="font-semibold text-slate-900">
                  {r0(f.rent_collected)} <span className="text-slate-500 font-normal">({pct(f.rent_collected, chargedTotal)}%)</span>
                </span>
              </p>
              <p className="flex justify-between gap-4">
                <span className="text-slate-600">
                  <span className="inline-block w-2 h-2 rounded-full mr-2" style={{ background: C.red }} />
                  Missed — rider absent, became debt
                </span>
                <span className="font-semibold text-slate-900">
                  {r0(f.rent_missed)} <span className="text-slate-500 font-normal">({pct(f.rent_missed, chargedTotal)}%)</span>
                </span>
              </p>
            </div>
            <Ratio parts={[
              { value: f.rent_collected, color: C.aqua, label: 'Collected' },
              { value: f.rent_missed, color: C.red, label: 'Missed' },
            ]} />
          </div>
          <div>
            <p className="text-sm text-slate-500">What happened to rent debt in this window</p>
            <div className="mt-2 space-y-1.5 text-sm">
              <p className="flex justify-between gap-4">
                <span className="text-slate-600">
                  <span className="inline-block w-2 h-2 rounded-full mr-2" style={{ background: C.aqua }} />
                  Clawed back from later payouts
                </span>
                <span className="font-semibold text-emerald-300">{r0(f.arrears_recovered)}</span>
              </p>
              <p className="flex justify-between gap-4">
                <span className="text-slate-600">
                  <span className="inline-block w-2 h-2 rounded-full mr-2" style={{ background: C.blue }} />
                  Written off — EV was actually returned
                </span>
                <span className="font-semibold text-slate-900">{r0(f.written_off)}</span>
              </p>
              <p className="flex justify-between gap-4">
                <span className="text-slate-600">
                  <span className="inline-block w-2 h-2 rounded-full mr-2" style={{ background: '#a78bfa' }} />
                  Covered by security deposits (EV closed)
                </span>
                <span className="font-semibold text-slate-900">{r0(f.deposit_applied)}</span>
              </p>
              {f.credit_offset > 0 && (
                <p className="flex justify-between gap-4">
                  <span className="text-slate-600 pl-4">…settled from credit balances</span>
                  <span className="text-slate-700">{r0(f.credit_offset)}</span>
                </p>
              )}
              {f.refunded > 0 && (
                <p className="flex justify-between gap-4">
                  <span className="text-slate-600 pl-4">…refunded to riders (over-charged)</span>
                  <span className="text-slate-700">{r0(f.refunded)}</span>
                </p>
              )}
              <p className="flex justify-between gap-4 pt-1 border-t border-edge-soft">
                <span className="text-slate-600">Net change in what's owed</span>
                <span className={'font-semibold ' + (stillOwedDelta > 0 ? 'text-red-300' : 'text-emerald-300')}>
                  {stillOwedDelta > 0 ? '+' : ''}{r0(stillOwedDelta)}
                </span>
              </p>
            </div>
            <Ratio parts={[
              { value: f.arrears_recovered, color: C.aqua, label: 'Recovered' },
              { value: f.written_off, color: C.blue, label: 'Written off' },
              { value: f.deposit_applied, color: '#a78bfa', label: 'Deposit' },
              { value: Math.max(0, stillOwedDelta), color: C.red, label: 'Still owed' },
            ]} />
          </div>
        </div>
      </div>

      {/* 3 · where the debt stands TODAY (live, not window-scoped) */}
      <div className="flex flex-wrap items-stretch gap-3 mb-5">
        <Big label="Rent debt outstanding (today)" value={r0(p.ev_arrears)}
             onClick={() => setDrill('total_arrears')}
             tone={p.ev_arrears > 0 ? 'bad' : 'good'}
             sub={
               <>
                 {r0(p.ev_arrears_active)} owed by current EV holders
                 {p.ev_arrears_dormant > 0 && (
                   <> · {r0(p.ev_arrears_dormant)} dormant ({p.dormant_riders} rider
                   {p.dormant_riders === 1 ? '' : 's'} who returned the EV — future payouts held)</>
                 )}
               </>
             } />
        <Big label="Other dues owed by riders" value={r0(p.dues)} sub={<>carry-forward balances</>}
             onClick={() => navigate('/arrears?bucket=dues')} />
        <Big label="Credit riders hold with us" value={r0(p.credit)} sub={<>auto-offsets new arrears</>}
             onClick={() => setDrill('credit_balances')} />
        <Big label="COD not yet cleared" value={r0(p.cod_uncleared)} sub={<>payouts held until cleared</>}
             onClick={() => setDrill('cod_uncleared')} />
      </div>

      <DebtAging suffix={suffix} />
      <TrendCharts suffix={suffix} />
      {drill && (
        <BreakdownDrawer metric={drill} suffix={suffix} onClose={() => setDrill(null)} />
      )}
    </>
  )
}

function DebtAging({ suffix }: { suffix: string }) {
  const { data } = useApi<{ aging: AgingBucket[] }>(
    '/dashboard/collection' + (suffix ? suffix + '&weeks=12' : '?weeks=12'),
  )
  const buckets = data?.aging ?? []
  const max = Math.max(...buckets.map((b) => b.outstanding), 1)
  if (!buckets.some((b) => b.riders > 0)) return null
  return (
    <div className="panel p-5 mb-5">
      <h2 className="font-display font-semibold text-slate-900 mb-1">How old is the debt?</h2>
      <p className="text-xs text-slate-500 mb-3">
        Money in the 60d+ bucket rarely comes back on its own — chase those first.
      </p>
      <div className="space-y-2 max-w-xl">
        {buckets.map((b) => (
          <div key={b.bucket} className="flex items-center gap-3 text-sm">
            <span className="w-14 shrink-0 text-slate-500">{b.bucket}</span>
            <div className="flex-1 h-3.5 bg-white/[0.05] rounded overflow-hidden">
              <div className="h-full rounded" style={{
                width: `${(b.outstanding / max) * 100}%`,
                background: b.bucket === '60d+' ? C.red : C.blue,
              }} />
            </div>
            <span className="w-24 text-right font-mono text-slate-800">{r0(b.outstanding)}</span>
            <span className="w-16 text-right text-xs text-slate-500">
              {b.riders} rider{b.riders === 1 ? '' : 's'}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

function TrendCharts({ suffix }: { suffix: string }) {
  const { data } = useApi<{ weeks: TrendWeek[] }>(
    '/dashboard/trends' + (suffix ? suffix + '&weeks=12' : '?weeks=12'),
  )
  const weeks = data?.weeks ?? []
  const labels = weeks.map((w) => w.week_start.slice(5))
  if (!weeks.length) return null
  return (
    <div className="grid lg:grid-cols-2 gap-4">
      <div className="panel p-4">
        <div className="flex items-baseline justify-between mb-1">
          <h3 className="font-semibold text-slate-900 text-sm">Money to riders, weekly</h3>
          <span className="text-xs text-slate-500">last 12 weeks</span>
        </div>
        <LineChart labels={labels} series={[
          { key: 'g', label: 'Came in', color: C.blue, values: weeks.map((w) => w.gross_payout) },
          { key: 'r', label: 'Paid out', color: C.aqua, values: weeks.map((w) => w.released) },
        ]} height="h-44" />
      </div>
      <div className="panel p-4">
        <div className="flex items-baseline justify-between mb-1">
          <h3 className="font-semibold text-slate-900 text-sm">Rent collected vs missed, weekly</h3>
          <span className="text-xs text-slate-500">last 12 weeks</span>
        </div>
        <LineChart labels={labels} series={[
          { key: 'c', label: 'Collected', color: C.aqua, values: weeks.map((w) => w.rent_collected) },
          { key: 'm', label: 'Missed', color: C.red, values: weeks.map((w) => w.rent_missed) },
        ]} height="h-44" />
      </div>
    </div>
  )
}

// ── dimension tables (numbers first, sortable) ───────────────────────────

const cell = 'px-3 py-2 text-right tabular-nums whitespace-nowrap'
const cellL = 'px-3 py-2 whitespace-nowrap'

function SkeletonTable({ cols = 8 }: { cols?: number }) {
  return (
    <div className="panel p-4 space-y-2.5">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="flex gap-3">
          <div className="skeleton h-4 w-40" />
          {Array.from({ length: cols - 1 }).map((_, j) => (
            <div key={j} className="skeleton h-4 flex-1" />
          ))}
        </div>
      ))}
    </div>
  )
}

function TableShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="panel overflow-x-auto">
      <table className="w-full text-sm">{children}</table>
    </div>
  )
}

function CompaniesTab({ suffix }: { suffix: string }) {
  const { data, loading, error } = useApi<{ rows: CompanyRow[] }>(
    '/dashboard/story/by' + (suffix ? suffix + '&dim=company' : '?dim=company'),
  )
  const { sorted, sortKey, sortDir, toggleSort } = useSort(data?.rows ?? [], { urlKey: 'csort' })
  if (loading && !data) return <SkeletonTable cols={9} />
  if (error) return <p className="text-red-400">{error}</p>
  return (
    <>
      <p className="text-sm text-slate-500 mb-3">
        Each company's window: what they sent, what riders got, and how their rent behaved.
        <span className="text-slate-400"> "Owed now" is live, not window-scoped.</span>
      </p>
      <TableShell>
        <thead className="text-left border-b border-edge-soft">
          <tr>
            <SortableTh tag="company" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Company</SortableTh>
            <SortableTh tag="riders" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Riders paid</SortableTh>
            <SortableTh tag="gross_payout" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Came in</SortableTh>
            <SortableTh tag="released" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Paid out</SortableTh>
            <SortableTh tag="rent_collected" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Rent collected</SortableTh>
            <SortableTh tag="rent_missed" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Rent missed</SortableTh>
            <SortableTh tag="arrears_recovered" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Clawed back</SortableTh>
            <SortableTh tag="written_off" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Written off</SortableTh>
            <SortableTh tag="outstanding" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Owed now</SortableTh>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => {
            const charged = r.rent_collected + r.rent_missed
            return (
              <tr key={r.company} className="border-t border-edge-soft hover:bg-white/[0.02]">
                <td className={cellL + ' font-medium text-slate-900'}>{r.company}</td>
                <td className={cell}>{r.riders}</td>
                <td className={cell}>{r0(r.gross_payout)}</td>
                <td className={cell}>{r0(r.released)}</td>
                <td className={cell + ' text-emerald-300'}>
                  {r0(r.rent_collected)}
                  <MicroBar frac={charged > 0 ? r.rent_collected / charged : 0} />
                </td>
                <td className={cell + (r.rent_missed > 0 ? ' text-red-300' : '')}>{r0(r.rent_missed)}</td>
                <td className={cell}>{r0(r.arrears_recovered)}</td>
                <td className={cell}>{r0(r.written_off)}</td>
                <td className={cell + ((r.outstanding + r.dues) > 0 ? ' text-red-300' : '')}>
                  {r0(r.outstanding + r.dues)}
                </td>
              </tr>
            )
          })}
        </tbody>
        <tfoot>
          <tr className="border-t border-edge text-slate-900 font-semibold bg-white/[0.02]">
            <td className={cellL}>Total</td>
            <td className={cell}>{sorted.reduce((a, r) => a + r.riders, 0)}</td>
            <td className={cell}>{r0(sorted.reduce((a, r) => a + r.gross_payout, 0))}</td>
            <td className={cell}>{r0(sorted.reduce((a, r) => a + r.released, 0))}</td>
            <td className={cell}>{r0(sorted.reduce((a, r) => a + r.rent_collected, 0))}</td>
            <td className={cell}>{r0(sorted.reduce((a, r) => a + r.rent_missed, 0))}</td>
            <td className={cell}>{r0(sorted.reduce((a, r) => a + r.arrears_recovered, 0))}</td>
            <td className={cell}>{r0(sorted.reduce((a, r) => a + r.written_off, 0))}</td>
            <td className={cell}>{r0(sorted.reduce((a, r) => a + r.outstanding + r.dues, 0))}</td>
          </tr>
        </tfoot>
      </TableShell>
    </>
  )
}

function EvsTab({ suffix }: { suffix: string }) {
  const { data, loading, error } = useApi<{ rows: EvRow[] }>(
    '/dashboard/story/by' + (suffix ? suffix + '&dim=ev' : '?dim=ev'),
  )
  const { sorted, sortKey, sortDir, toggleSort } = useSort(data?.rows ?? [], { urlKey: 'esort' })
  if (loading && !data) return <SkeletonTable cols={9} />
  if (error) return <p className="text-red-400">{error}</p>
  return (
    <>
      <p className="text-sm text-slate-500 mb-3">
        Per EV for the window: rent it earned vs what the provider charges us. Negative margin =
        the EV cost more than it brought in.
      </p>
      <TableShell>
        <thead className="text-left border-b border-edge-soft">
          <tr>
            <SortableTh tag="ev_id" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>EV</SortableTh>
            <SortableTh tag="holder" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Holder</SortableTh>
            <SortableTh tag="charged" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Billed</SortableTh>
            <SortableTh tag="collected" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Collected</SortableTh>
            <SortableTh tag="missed" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Missed</SortableTh>
            <SortableTh tag="written_off" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Written off</SortableTh>
            <SortableTh tag="provider_cost" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>We owe provider</SortableTh>
            <SortableTh tag="margin" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Margin</SortableTh>
            <SortableTh tag="status" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Status</SortableTh>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr key={r.ev_id} className="border-t border-edge-soft hover:bg-white/[0.02]">
              <td className={cellL}>
                <Link to={'/evs/' + encodeURIComponent(r.ev_id)} className="text-brand-300 hover:underline">
                  {r.ev_id}
                </Link>
                <span className="text-xs text-slate-500 ml-2">{r.provider} {r.model}</span>
              </td>
              <td className={cellL}>
                {r.holder_person_id
                  ? <Link to={'/persons/' + r.holder_person_id} className="text-slate-800 hover:text-brand-300">{r.holder}</Link>
                  : <span className="text-slate-500">—</span>}
              </td>
              <td className={cell}>{r0(r.charged)}</td>
              <td className={cell + ' text-emerald-300'}>
                {r0(r.collected)}
                <MicroBar frac={r.charged > 0 ? r.collected / r.charged : 0} />
              </td>
              <td className={cell + (r.missed > 0 ? ' text-red-300' : '')}>{r0(r.missed)}</td>
              <td className={cell}>{r0(r.written_off)}</td>
              <td className={cell}>{r0(r.provider_cost)}</td>
              <td className={cell + ' font-semibold ' + (r.margin < 0 ? 'text-red-300' : 'text-emerald-300')}>
                {r.margin < 0 ? '−' : ''}{r0(Math.abs(r.margin))}
              </td>
              <td className={cellL}>
                <span className={'pill ' + (r.status === 'in_use' ? 'bg-emerald-500/15 text-emerald-300'
                  : r.status === 'returned' ? 'bg-white/[0.06] text-slate-500'
                  : 'bg-amber-500/15 text-amber-300')}>
                  {r.status}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t border-edge text-slate-900 font-semibold bg-white/[0.02]">
            <td className={cellL} colSpan={2}>Total ({sorted.length} EVs)</td>
            <td className={cell}>{r0(sorted.reduce((a, r) => a + r.charged, 0))}</td>
            <td className={cell}>{r0(sorted.reduce((a, r) => a + r.collected, 0))}</td>
            <td className={cell}>{r0(sorted.reduce((a, r) => a + r.missed, 0))}</td>
            <td className={cell}>{r0(sorted.reduce((a, r) => a + r.written_off, 0))}</td>
            <td className={cell}>{r0(sorted.reduce((a, r) => a + r.provider_cost, 0))}</td>
            <td className={cell}>{r0(sorted.reduce((a, r) => a + r.margin, 0))}</td>
            <td className={cellL} />
          </tr>
        </tfoot>
      </TableShell>
    </>
  )
}

function RidersTab({ suffix }: { suffix: string }) {
  const { data, loading, error } = useApi<{ rows: RiderRow[] }>(
    '/dashboard/story/by' + (suffix ? suffix + '&dim=rider' : '?dim=rider'),
  )
  const [q, setQ] = useUrlStringSafe('rq')
  const rows = (data?.rows ?? []).filter((r) =>
    !q.trim() || (r.display_name + ' ' + (r.company ?? '') + ' ' + r.person_id)
      .toLowerCase().includes(q.trim().toLowerCase()),
  )
  const { sorted, sortKey, sortDir, toggleSort } = useSort(rows, { urlKey: 'rsort' })
  if (loading && !data) return <SkeletonTable cols={8} />
  if (error) return <p className="text-red-400">{error}</p>
  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <p className="text-sm text-slate-500">
          Per rider for the window. <span className="text-slate-400">"Owes now" = live EV debt + dues.</span>
        </p>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter riders…"
               className="border rounded-lg px-3 py-1.5 text-sm w-56" />
      </div>
      <TableShell>
        <thead className="text-left border-b border-edge-soft">
          <tr>
            <SortableTh tag="display_name" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Rider</SortableTh>
            <SortableTh tag="gross_payout" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Earned</SortableTh>
            <SortableTh tag="released" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Took home</SortableTh>
            <SortableTh tag="rent_collected" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Rent paid</SortableTh>
            <SortableTh tag="rent_missed" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Rent missed</SortableTh>
            <SortableTh tag="arrears_recovered" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Clawed back</SortableTh>
            <SortableTh tag="written_off" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Written off</SortableTh>
            <SortableTh tag="outstanding" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Owes now</SortableTh>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => {
            const owes = r.outstanding + Math.max(0, -r.balance)
            return (
              <tr key={r.person_id} className="border-t border-edge-soft hover:bg-white/[0.02]">
                <td className={cellL}>
                  <Link to={'/persons/' + r.person_id} className="text-slate-900 hover:text-brand-300 font-medium">
                    {r.display_name}
                  </Link>
                  <span className="text-xs text-slate-500 ml-2">{r.company}</span>
                </td>
                <td className={cell}>{r0(r.gross_payout)}</td>
                <td className={cell + ' text-emerald-300'}>{r0(r.released)}</td>
                <td className={cell}>{r0(r.rent_collected)}</td>
                <td className={cell + (r.rent_missed > 0 ? ' text-red-300' : '')}>{r0(r.rent_missed)}</td>
                <td className={cell}>{r0(r.arrears_recovered)}</td>
                <td className={cell}>{r0(r.written_off)}</td>
                <td className={cell + ' font-semibold ' + (owes > 0 ? 'text-red-300' : 'text-slate-500')}>
                  {r0(owes)}
                </td>
              </tr>
            )
          })}
        </tbody>
        <tfoot>
          <tr className="border-t border-edge text-slate-900 font-semibold bg-white/[0.02]">
            <td className={cellL}>Total ({sorted.length} riders)</td>
            <td className={cell}>{r0(sorted.reduce((a, r) => a + r.gross_payout, 0))}</td>
            <td className={cell}>{r0(sorted.reduce((a, r) => a + r.released, 0))}</td>
            <td className={cell}>{r0(sorted.reduce((a, r) => a + r.rent_collected, 0))}</td>
            <td className={cell}>{r0(sorted.reduce((a, r) => a + r.rent_missed, 0))}</td>
            <td className={cell}>{r0(sorted.reduce((a, r) => a + r.arrears_recovered, 0))}</td>
            <td className={cell}>{r0(sorted.reduce((a, r) => a + r.written_off, 0))}</td>
            <td className={cell}>
              {r0(sorted.reduce((a, r) => a + r.outstanding + Math.max(0, -r.balance), 0))}
            </td>
          </tr>
        </tfoot>
      </TableShell>
    </>
  )
}

// Local alias so the riders filter lives in the URL like everything else.
function useUrlStringSafe(key: string) {
  return useUrlString(key)
}
