/**
 * Analytics → Recruiters — the field staff as a subject, best to worst.
 *
 * Two views in one route. The **board** is every recruiter as a card plus the
 * same rows as a sortable table: who signed up how many riders, how many of
 * them are still working, and how far the person rode doing it. The table is
 * the argument, the cards are the way in.
 *
 * The **detail** view is one recruiter: their onboardings over time at three
 * grains, the riders behind the number, the EVs they handed over, and their
 * odometer — which is not ledger money but *is* the basis of a fuel payment
 * made outside the system, so it is shown as evidence: monthly totals first,
 * unclosed days flagged, and a link to the dash photo behind each reading.
 *
 * Everything here reads. Nothing on this page writes, and the sensitive half
 * of a profile arrives already masked from the server — the console never asks
 * for it in full and never offers to reveal it.
 *
 * Every request goes through `useApi`, which follows the live cursor on its
 * own, so a rider onboarded from a phone appears here without a reload.
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { useAuth } from '../auth/AuthContext'
import { Spinner } from '../components/Spinner'
import { SortableTh, useSort } from '../components/Sortable'
import { useUrlNumber, useUrlString } from '../state/useUrlState'
import { integer } from '../lib/format'
import { C, LineChart } from './dashboard/charts'

// ── API shapes ───────────────────────────────────────────────────────────

interface BoardRow {
  email: string
  name: string
  zone: string | null
  is_active: boolean
  has_photo: boolean
  onboarded_all_time: number
  onboarded_recent: number
  onboarded_month: number
  still_working: number
  evs_deployed: number
  evs_deployed_recent: number
  km_this_month: number
  retention_pct: number | null
}
interface Board {
  since: string
  window_days: number
  active_within_days: number
  recruiters: BoardRow[]
}

interface Bucket {
  bucket: string
  onboarded: number
  still_working: number
  evs_deployed: number
  km: number
}
interface SeriesPayload {
  email: string
  grain: string
  active_within_days: number
  series: Bucket[]
  totals: { onboarded: number; still_working: number; evs_deployed: number; km: number }
}

interface RiderRow {
  rider_id: string
  company_name: string | null
  name: string | null
  person_id: number
  hub: string | null
  created_at: string | null
  on_roster: boolean
  working: boolean
  last_worked_on: string | null
}

interface EvRow {
  assignment_id: number
  ev_id: string
  person_id: number
  rider_name: string | null
  handover_date: string | null
  returned_date: string | null
  returned_by: string | null
  still_held: boolean
  model: string | null
  provider: string | null
}

interface ShiftDay {
  id: number
  day: string
  start_km: number | null
  end_km: number | null
  distance_km: number | null
  start_at: string | null
  end_at: string | null
  has_start_photo: boolean
  has_end_photo: boolean
  note: string | null
  complete: boolean
}
interface ShiftsPayload {
  since: string
  days: ShiftDay[]
  total_km: number
  days_recorded: number
  average_km: number | null
  incomplete: string[]
}
interface MonthRow {
  month: string
  km: number
  days_recorded: number
  days_open: number
}

interface Profile {
  email: string
  full_name: string | null
  display_name: string | null
  phone: string | null
  address: string | null
  account_name: string | null
  account_no: string | null
  ifsc: string | null
  bank_name: string | null
  aadhaar_no: string | null
  pan_no: string | null
  role: string | null
  zone: string | null
  is_active: boolean
  has_photo: boolean
  updated_at: string | null
  /** The server decided these came back as `••••1234`. There is no way to ask
   *  for more, and the UI must not pretend otherwise. */
  masked: boolean
}

const TABS = [
  ['numbers', 'Numbers'],
  ['riders', 'Riders'],
  ['evs', 'EVs'],
  ['odometer', 'Odometer'],
  ['profile', 'Profile'],
] as const

const GRAINS = [
  ['day', 'Day'],
  ['week', 'Week'],
  ['month', 'Month'],
] as const

/** How many buckets each grain asks for — a day view wants a month of days,
 *  a month view wants a year. Not URL state: it follows from the grain. */
const BUCKETS: Record<string, number> = { day: 30, week: 16, month: 12 }

const cell = 'px-3 py-2 text-right tabular-nums whitespace-nowrap'
const cellL = 'px-3 py-2 whitespace-nowrap'

const enc = (email: string) => encodeURIComponent(email)
const photoUrl = (email: string) => `/api/recruiters/${enc(email)}/photo`
const pct = (v: number | null) => (v === null ? '—' : `${v}%`)
/** A name we can always show: the profile name, else the email's local part. */
const shortName = (email: string, name?: string | null) => name || email.split('@')[0]

// ── small building blocks ────────────────────────────────────────────────

function Chip({ active, onClick, children, title }: {
  active: boolean; onClick: () => void; children: React.ReactNode; title?: string
}) {
  return (
    <button onClick={onClick} title={title}
      className={'px-2.5 py-1 rounded-lg text-xs font-medium transition-colors ' +
        (active
          ? 'bg-brand-500/25 text-white shadow-[0_0_0_1px_rgba(139,92,246,0.4)]'
          : 'bg-white/[0.04] text-slate-500 hover:text-slate-800 hover:bg-white/[0.07]')}>
      {children}
    </button>
  )
}

function Stat({ label, value, sub, tone }: {
  label: string; value: string; sub?: React.ReactNode; tone?: 'good' | 'bad'
}) {
  return (
    <div className="panel p-4 flex-1 min-w-[150px]">
      <p className="text-xs text-slate-500">{label}</p>
      <p className={'text-2xl font-bold font-display mt-1 tracking-tight ' +
        (tone === 'good' ? 'text-emerald-300' : tone === 'bad' ? 'text-red-300' : 'text-slate-900')}>
        {value}
      </p>
      {sub && <div className="text-xs text-slate-500 mt-1.5 leading-5">{sub}</div>}
    </div>
  )
}

/** The recruiter's face, or their initials. `has_photo` says whether to ask at
 *  all; `onError` covers the object having gone missing from the store. */
function Avatar({ email, name, hasPhoto, size = 'h-12 w-12' }: {
  email: string; name: string; hasPhoto: boolean; size?: string
}) {
  const [broken, setBroken] = useState(false)
  const initials = name.split(/\s+/).filter(Boolean).slice(0, 2)
    .map((w) => w[0]?.toUpperCase()).join('')
  const shell = `${size} rounded-xl overflow-hidden bg-brand-500/15 ring-1 ring-white/10 ` +
                'grid place-items-center shrink-0 select-none'
  if (!hasPhoto || broken) {
    return <div className={shell}><span className="font-semibold text-brand-300">{initials || '?'}</span></div>
  }
  return (
    <div className={shell}>
      <img src={photoUrl(email)} alt={name} className="h-full w-full object-cover"
           onError={() => setBroken(true)} />
    </div>
  )
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="panel p-8 text-center text-sm text-slate-500">{children}</p>
}

function TableShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="panel overflow-x-auto">
      <table className="w-full text-sm">{children}</table>
    </div>
  )
}

function ZonePill({ zone }: { zone: string | null }) {
  if (!zone) return <span className="text-slate-500 text-xs">no zone</span>
  return (
    <span className={'pill ' + (zone === 'North' ? 'bg-sky-500/15 text-sky-300'
      : zone === 'South' ? 'bg-amber-500/15 text-amber-300'
      : 'bg-white/[0.06] text-slate-500')}>
      {zone}
    </span>
  )
}

// ── the page ─────────────────────────────────────────────────────────────

export function RecruitersPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin' || user?.role === 'creator'
  const [selected, setSelected] = useUrlString('r')
  const [days, setDays] = useUrlNumber('days', 30)

  const board = useApi<Board>(isAdmin ? `/recruiters?days=${days}` : null, [days])

  if (!isAdmin) {
    return (
      <div className="max-w-7xl mx-auto">
        <h1 className="page-title mb-1">Recruiters</h1>
        <Empty>
          This page reads every recruiter's record, so it is open to admins only.
        </Empty>
      </div>
    )
  }

  const rows = board.data?.recruiters ?? []
  const row = rows.find((r) => r.email === selected)

  return (
    <div className="max-w-7xl mx-auto pb-12">
      {selected ? (
        <RecruiterDetail email={selected} row={row} onBack={() => setSelected('')} />
      ) : (
        <>
          <div className="flex items-start justify-between flex-wrap gap-3 mb-4">
            <div>
              <h1 className="page-title">Recruiters</h1>
              <p className="text-slate-500 text-sm mt-0.5">
                {board.data
                  ? `${rows.length} in the field · "onboarded" counts ${board.data.since} onwards ` +
                    `· "still working" means a shift in the last ${board.data.active_within_days} days`
                  : 'Loading…'}
              </p>
            </div>
            <div className="flex gap-1">
              {[7, 30, 90].map((n) => (
                <Chip key={n} active={days === n} onClick={() => setDays(n)}>{n}d</Chip>
              ))}
            </div>
          </div>

          {board.loading && !board.data && <Spinner label="Counting onboardings…" />}
          {board.error && <p className="text-red-400">{board.error}</p>}
          {board.data && rows.length === 0 && (
            <Empty>No recruiter has onboarded anyone yet. Create one on the Users page and set their zone.</Empty>
          )}
          {rows.length > 0 && (
            <>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 mb-6">
                {rows.map((r) => (
                  <RecruiterCard key={r.email} r={r} days={days} onOpen={() => setSelected(r.email)} />
                ))}
              </div>
              <BoardTable rows={rows} days={days} onOpen={setSelected} />
            </>
          )}
        </>
      )}
    </div>
  )
}

// ── board ────────────────────────────────────────────────────────────────

function RecruiterCard({ r, days, onOpen }: { r: BoardRow; days: number; onOpen: () => void }) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen() } }}
      className="panel p-4 cursor-pointer transition hover:-translate-y-0.5 hover:shadow-pop
                 focus:outline-none focus:ring-2 focus:ring-brand-400"
    >
      <div className="flex items-center gap-3 mb-3">
        <Avatar email={r.email} name={r.name} hasPhoto={r.has_photo} />
        <div className="min-w-0">
          <p className="font-semibold text-slate-900 truncate">{shortName(r.email, r.name)}</p>
          <p className="text-xs text-slate-500 truncate">{r.email}</p>
          <div className="mt-1 flex items-center gap-1.5">
            <ZonePill zone={r.zone} />
            {!r.is_active && <span className="pill bg-red-500/15 text-red-300">inactive</span>}
          </div>
        </div>
      </div>
      <dl className="grid grid-cols-3 gap-x-3 gap-y-2 text-center">
        <Cell label={`${days}d`} value={integer(r.onboarded_recent)} big />
        <Cell label="all time" value={integer(r.onboarded_all_time)} />
        <Cell label="working" value={integer(r.still_working)} />
        <Cell label="retention" value={pct(r.retention_pct)} />
        <Cell label="EVs out" value={integer(r.evs_deployed)} />
        <Cell label="km / month" value={integer(r.km_this_month)} />
      </dl>
    </div>
  )
}

function Cell({ label, value, big }: { label: string; value: string; big?: boolean }) {
  return (
    <div>
      <dd className={'font-mono tabular-nums ' +
        (big ? 'text-xl font-bold text-brand-300' : 'text-base text-slate-900')}>
        {value}
      </dd>
      <dt className="text-[10px] uppercase tracking-wider text-slate-500">{label}</dt>
    </div>
  )
}

function BoardTable({ rows, days, onOpen }: {
  rows: BoardRow[]; days: number; onOpen: (email: string) => void
}) {
  // With no sort in the URL the rows keep the server's order, which is already
  // best first — onboardings in the window, then all time. Clicking a header
  // takes over from there (asc, desc, back to best-first).
  const { sorted, sortKey, sortDir, toggleSort } = useSort(rows, { urlKey: 'sort' })
  return (
    <>
      <p className="text-sm text-slate-500 mb-3">
        Best to worst. Unsorted, the order is the one the server picks — onboardings in the last{' '}
        {days} days. Click any column to argue with it.
      </p>
      <TableShell>
        <thead className="text-left border-b border-edge-soft">
          <tr>
            <SortableTh tag="name" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Recruiter</SortableTh>
            <SortableTh tag="zone" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Zone</SortableTh>
            <SortableTh tag="onboarded_recent" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>
              Onboarded ({days}d)
            </SortableTh>
            <SortableTh tag="onboarded_month" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>This month</SortableTh>
            <SortableTh tag="onboarded_all_time" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>All time</SortableTh>
            <SortableTh tag="still_working" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Still working</SortableTh>
            <SortableTh tag="retention_pct" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Retention</SortableTh>
            <SortableTh tag="evs_deployed" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>EVs deployed</SortableTh>
            <SortableTh tag="km_this_month" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Km this month</SortableTh>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr key={r.email} onClick={() => onOpen(r.email)}
                className={'border-t border-edge-soft hover:bg-white/[0.02] cursor-pointer' +
                  (r.is_active ? '' : ' opacity-60')}>
              <td className={cellL}>
                <button onClick={(e) => { e.stopPropagation(); onOpen(r.email) }}
                        className="font-medium text-slate-900 hover:text-brand-300 underline
                                   decoration-dotted underline-offset-2"
                        title={'Open ' + r.email}>
                  {shortName(r.email, r.name)}
                </button>
                <span className="text-xs text-slate-500 ml-2">{r.email}</span>
              </td>
              <td className={cellL}><ZonePill zone={r.zone} /></td>
              <td className={cell + ' font-semibold'}>{integer(r.onboarded_recent)}</td>
              <td className={cell}>{integer(r.onboarded_month)}</td>
              <td className={cell}>{integer(r.onboarded_all_time)}</td>
              <td className={cell + ' text-emerald-300'}>{integer(r.still_working)}</td>
              <td className={cell}>{pct(r.retention_pct)}</td>
              <td className={cell}>{integer(r.evs_deployed)}</td>
              <td className={cell}>{integer(r.km_this_month)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t border-edge text-slate-900 font-semibold bg-white/[0.02]">
            <td className={cellL} colSpan={2}>Total ({sorted.length})</td>
            <td className={cell}>{integer(sorted.reduce((a, r) => a + r.onboarded_recent, 0))}</td>
            <td className={cell}>{integer(sorted.reduce((a, r) => a + r.onboarded_month, 0))}</td>
            <td className={cell}>{integer(sorted.reduce((a, r) => a + r.onboarded_all_time, 0))}</td>
            <td className={cell}>{integer(sorted.reduce((a, r) => a + r.still_working, 0))}</td>
            <td className={cell} />
            <td className={cell}>{integer(sorted.reduce((a, r) => a + r.evs_deployed, 0))}</td>
            <td className={cell}>{integer(sorted.reduce((a, r) => a + r.km_this_month, 0))}</td>
          </tr>
        </tfoot>
      </TableShell>
    </>
  )
}

// ── detail ───────────────────────────────────────────────────────────────

function RecruiterDetail({ email, row, onBack }: {
  email: string; row: BoardRow | undefined; onBack: () => void
}) {
  const [tab, setTab] = useUrlString('tab', 'numbers')
  // The header needs a name, a zone and a face even on a deep link, where the
  // board row for this person may not have arrived (or may not exist at all).
  const profile = useApi<Profile>(`/recruiters/${enc(email)}/profile`, [email])
  const p = profile.data
  const name = shortName(email, row?.name ?? p?.full_name ?? p?.display_name)
  const zone = row?.zone ?? p?.zone ?? null
  const hasPhoto = row?.has_photo ?? p?.has_photo ?? false
  const isActive = row?.is_active ?? p?.is_active ?? true

  return (
    <>
      <button onClick={onBack} className="text-sm text-brand-300 hover:underline mb-3">
        ← All recruiters
      </button>

      <div className="flex items-center gap-4 flex-wrap mb-5">
        <Avatar email={email} name={name} hasPhoto={hasPhoto} size="h-16 w-16" />
        <div>
          <h1 className="page-title">{name}</h1>
          <p className="text-slate-500 text-sm mt-0.5 flex items-center gap-2 flex-wrap">
            <span>{email}</span>
            <ZonePill zone={zone} />
            {p?.role && <span className="pill bg-white/[0.06] text-slate-500">{p.role}</span>}
            {!isActive && <span className="pill bg-red-500/15 text-red-300">inactive</span>}
          </p>
        </div>
      </div>

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

      {tab === 'numbers' && <NumbersTab email={email} />}
      {tab === 'riders' && <RidersTab email={email} />}
      {tab === 'evs' && <EvsTab email={email} />}
      {tab === 'odometer' && <OdometerTab email={email} />}
      {tab === 'profile' && <ProfileTab state={profile} />}
    </>
  )
}

// ── Numbers ──────────────────────────────────────────────────────────────

function NumbersTab({ email }: { email: string }) {
  const [grain, setGrain] = useUrlString('grain', 'week')
  const buckets = BUCKETS[grain] ?? 12
  const { data, loading, error } = useApi<SeriesPayload>(
    `/recruiters/${enc(email)}/series?grain=${grain}&buckets=${buckets}`,
    [email, grain, buckets],
  )

  if (loading && !data) return <Spinner label="Building the series…" />
  if (error) return <p className="text-red-400">{error}</p>
  const series = data?.series ?? []
  // Month buckets are already short; a day/week bucket is an ISO date and only
  // its month-day half fits under a tick.
  const labels = series.map((s) => (grain === 'month' ? s.bucket : s.bucket.slice(5)))
  const t = data?.totals

  return (
    <>
      <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
        <p className="text-sm text-slate-500">
          {/* The server drops buckets in which nothing at all happened, so what
              came back is usually shorter than what was asked for — say the
              number that is actually on the chart, not the request. */}
          Onboardings per {grain} — the last {series.length} with anything recorded, of{' '}
          {buckets} asked for.{' '}
          <span className="text-slate-400">
            "Still working" is a cohort figure: of the riders signed up in that bucket, how many are
            working <em>now</em> (a shift within {data?.active_within_days ?? 12} days) — not how many
            were working back then.
          </span>
        </p>
        <div className="flex gap-1">
          {GRAINS.map(([key, label]) => (
            <Chip key={key} active={grain === key} onClick={() => setGrain(key)}>{label}</Chip>
          ))}
        </div>
      </div>

      {t && (
        <div className="flex flex-wrap items-stretch gap-3 mb-5">
          <Stat label="Onboarded" value={integer(t.onboarded)}
                sub={<>across these {series.length} {grain === 'day' ? 'days' : grain + 's'}</>} />
          <Stat label="Still working" value={integer(t.still_working)} tone="good"
                sub={<>{t.onboarded > 0 ? Math.round((t.still_working / t.onboarded) * 100) : 0}% of them</>} />
          <Stat label="EVs deployed" value={integer(t.evs_deployed)} />
          <Stat label="Distance" value={integer(t.km) + ' km'} sub={<>odometer, same buckets</>} />
        </div>
      )}

      {series.length === 0 ? (
        <Empty>Nothing recorded for this recruiter yet — no onboardings, no EVs, no odometer.</Empty>
      ) : (
        <>
          <div className="panel p-4 mb-4">
            <div className="flex items-baseline justify-between mb-1">
              <h3 className="font-semibold text-slate-900 text-sm">Onboarded, and how many stuck</h3>
              <span className="text-xs text-slate-500">per {grain}</span>
            </div>
            {/* The chart primitive draws into a fixed 720×220 viewBox, so a
                full-width panel needs a height near a third of its width or
                the plot letterboxes into the middle of the card. */}
            <LineChart labels={labels} format={integer} height="h-96" series={[
              { key: 'on', label: 'Onboarded', color: C.blue, values: series.map((s) => s.onboarded) },
              { key: 'sw', label: 'Still working', color: C.aqua, values: series.map((s) => s.still_working) },
            ]} />
          </div>

          <div className="grid lg:grid-cols-2 gap-4 mb-4">
            <div className="panel p-4">
              <div className="flex items-baseline justify-between mb-1">
                <h3 className="font-semibold text-slate-900 text-sm">Distance ridden</h3>
                <span className="text-xs text-slate-500">km per {grain}</span>
              </div>
              <LineChart labels={labels} format={(v) => integer(v) + ' km'} height="h-44" series={[
                { key: 'km', label: 'Km', color: C.orange, values: series.map((s) => s.km) },
              ]} />
            </div>
            <div className="panel p-4">
              <div className="flex items-baseline justify-between mb-1">
                <h3 className="font-semibold text-slate-900 text-sm">EVs handed over</h3>
                <span className="text-xs text-slate-500">per {grain}</span>
              </div>
              <LineChart labels={labels} format={integer} height="h-44" series={[
                { key: 'ev', label: 'EVs', color: C.blue, values: series.map((s) => s.evs_deployed) },
              ]} />
            </div>
          </div>

          {/* Every chart in this app is paired with the numbers behind it. */}
          <TableShell>
            <thead className="text-left border-b border-edge-soft">
              <tr>
                <th className="px-3 py-2 font-medium text-xs">Bucket</th>
                <th className="px-3 py-2 font-medium text-xs text-right">Onboarded</th>
                <th className="px-3 py-2 font-medium text-xs text-right">Still working</th>
                <th className="px-3 py-2 font-medium text-xs text-right">EVs</th>
                <th className="px-3 py-2 font-medium text-xs text-right">Km</th>
              </tr>
            </thead>
            <tbody>
              {[...series].reverse().map((s) => (
                <tr key={s.bucket} className="border-t border-edge-soft hover:bg-white/[0.02]">
                  <td className={cellL}>{s.bucket}</td>
                  <td className={cell}>{integer(s.onboarded)}</td>
                  <td className={cell + ' text-emerald-300'}>{integer(s.still_working)}</td>
                  <td className={cell}>{integer(s.evs_deployed)}</td>
                  <td className={cell}>{integer(s.km)}</td>
                </tr>
              ))}
            </tbody>
          </TableShell>
        </>
      )}
    </>
  )
}

// ── Riders ───────────────────────────────────────────────────────────────

const RIDER_FILTERS = [
  ['all', 'All'],
  ['working', 'Working'],
  ['idle', 'Idle'],
] as const

function RidersTab({ email }: { email: string }) {
  const [status, setStatus] = useUrlString('rstatus', 'all')
  const { data, loading, error } = useApi<RiderRow[]>(
    `/recruiters/${enc(email)}/riders?status=${status}`,
    [email, status],
  )
  const { sorted, sortKey, sortDir, toggleSort } = useSort(data ?? [], { urlKey: 'rsort' })

  return (
    <>
      <div className="flex items-center justify-between flex-wrap gap-3 mb-3">
        <p className="text-sm text-slate-500">
          Everyone this recruiter signed up, newest first. "Idle" is not "gone" — it means no shift
          has been recorded recently, which is the same rule the retention number uses.
        </p>
        <div className="flex gap-1">
          {RIDER_FILTERS.map(([key, label]) => (
            <Chip key={key} active={status === key} onClick={() => setStatus(key)}>{label}</Chip>
          ))}
        </div>
      </div>

      {loading && !data && <Spinner />}
      {error && <p className="text-red-400">{error}</p>}
      {data && sorted.length === 0 && (
        <Empty>
          {status === 'all'
            ? 'This recruiter has not onboarded anyone yet.'
            : `Nobody they onboarded is ${status} right now.`}
        </Empty>
      )}
      {sorted.length > 0 && (
        <TableShell>
          <thead className="text-left border-b border-edge-soft">
            <tr>
              <SortableTh tag="rider_id" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Rider id</SortableTh>
              <SortableTh tag="name" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Name</SortableTh>
              <SortableTh tag="company_name" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Company</SortableTh>
              <SortableTh tag="hub" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Hub</SortableTh>
              <SortableTh tag="created_at" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Onboarded</SortableTh>
              <SortableTh tag="last_worked_on" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Last worked</SortableTh>
              <SortableTh tag="working" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>State</SortableTh>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r) => (
              <tr key={r.rider_id + ':' + r.person_id} className="border-t border-edge-soft hover:bg-white/[0.02]">
                <td className={cellL + ' font-mono text-xs'}>{r.rider_id}</td>
                <td className={cellL}>
                  <Link to={'/persons/' + r.person_id} className="text-slate-900 hover:text-brand-300 font-medium">
                    {r.name ?? `#${r.person_id}`}
                  </Link>
                </td>
                <td className={cellL}>{r.company_name ?? '—'}</td>
                <td className={cellL}>{r.hub ?? <span className="text-slate-500">—</span>}</td>
                <td className={cellL + ' text-xs text-slate-600'}>{r.created_at?.slice(0, 10) ?? '—'}</td>
                <td className={cellL + ' text-xs text-slate-600'}>
                  {r.last_worked_on?.slice(0, 10) ?? <span className="text-slate-500">never</span>}
                </td>
                <td className={cellL}>
                  <span className={'pill ' + (r.working ? 'bg-emerald-500/15 text-emerald-300'
                    : 'bg-white/[0.06] text-slate-500')}>
                    {r.working ? 'working' : 'idle'}
                  </span>
                  {!r.on_roster && (
                    <span className="pill bg-amber-500/15 text-amber-300 ml-1.5"
                          title="Off the company roster — the file stopped listing them">
                      off roster
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </TableShell>
      )}
    </>
  )
}

// ── EVs ──────────────────────────────────────────────────────────────────

function EvsTab({ email }: { email: string }) {
  const { data, loading, error } = useApi<EvRow[]>(`/recruiters/${enc(email)}/evs`, [email])
  const { sorted, sortKey, sortDir, toggleSort } = useSort(data ?? [], { urlKey: 'esort' })

  if (loading && !data) return <Spinner />
  if (error) return <p className="text-red-400">{error}</p>
  if (sorted.length === 0) {
    return (
      <Empty>
        No EV handovers recorded for this recruiter. Attribution comes from the assignment row, so
        handovers made before that was tracked simply carry no name.
      </Empty>
    )
  }
  const held = sorted.filter((e) => e.still_held).length
  return (
    <>
      <p className="text-sm text-slate-500 mb-3">
        {integer(sorted.length)} handover{sorted.length === 1 ? '' : 's'}, {integer(held)} still out.
      </p>
      <TableShell>
        <thead className="text-left border-b border-edge-soft">
          <tr>
            <SortableTh tag="ev_id" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>EV</SortableTh>
            <SortableTh tag="model" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Model</SortableTh>
            <SortableTh tag="provider" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Provider</SortableTh>
            <SortableTh tag="rider_name" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Held by</SortableTh>
            <SortableTh tag="handover_date" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Handed over</SortableTh>
            <SortableTh tag="returned_date" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Returned</SortableTh>
            <SortableTh tag="still_held" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>State</SortableTh>
          </tr>
        </thead>
        <tbody>
          {sorted.map((e) => (
            <tr key={e.assignment_id} className="border-t border-edge-soft hover:bg-white/[0.02]">
              <td className={cellL}>
                <Link to={'/evs/' + enc(e.ev_id)} className="text-brand-300 hover:underline font-mono text-xs">
                  {e.ev_id}
                </Link>
              </td>
              <td className={cellL}>{e.model ?? '—'}</td>
              <td className={cellL}>{e.provider ?? '—'}</td>
              <td className={cellL}>
                <Link to={'/persons/' + e.person_id} className="text-slate-900 hover:text-brand-300">
                  {e.rider_name ?? `#${e.person_id}`}
                </Link>
              </td>
              <td className={cellL + ' text-xs text-slate-600'}>{e.handover_date?.slice(0, 10) ?? '—'}</td>
              <td className={cellL + ' text-xs text-slate-600'}>
                {e.returned_date?.slice(0, 10) ?? <span className="text-slate-500">—</span>}
              </td>
              <td className={cellL}>
                <span className={'pill ' + (e.still_held ? 'bg-emerald-500/15 text-emerald-300'
                  : 'bg-white/[0.06] text-slate-500')}>
                  {e.still_held ? 'still held' : 'returned'}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </TableShell>
    </>
  )
}

// ── Odometer ─────────────────────────────────────────────────────────────

function OdometerTab({ email }: { email: string }) {
  const [days, setDays] = useUrlNumber('odays', 30)
  const monthly = useApi<{ months: MonthRow[] }>(`/recruiters/${enc(email)}/shifts/monthly?months=12`, [email])
  const daily = useApi<ShiftsPayload>(`/recruiters/${enc(email)}/shifts?days=${days}`, [email, days])

  const months = monthly.data?.months ?? []
  const rows = daily.data?.days ?? []
  const openTotal = months.reduce((a, m) => a + m.days_open, 0)
  const current = months[0]

  if (monthly.loading && !monthly.data) return <Spinner label="Reading the odometer…" />
  if (monthly.error) return <p className="text-red-400">{monthly.error}</p>

  return (
    <>
      <p className="text-sm text-slate-500 mb-4">
        The fuel claim is paid on the monthly total. Only a day with <em>both</em> readings counts —
        an unclosed day contributes nothing, which is why the open count sits next to every month
        rather than being folded quietly into it.
      </p>

      {months.length === 0 ? (
        <Empty>No odometer readings yet. Readings are recorded from the recruiter's phone at the start and end of a day.</Empty>
      ) : (
        <>
          <div className="flex flex-wrap items-stretch gap-3 mb-5">
            <Stat label={`This month (${current.month})`} value={integer(current.km) + ' km'}
                  sub={<>{integer(current.days_recorded)} day{current.days_recorded === 1 ? '' : 's'} closed</>} />
            <Stat label="Last 12 months" value={integer(months.reduce((a, m) => a + m.km, 0)) + ' km'}
                  sub={<>{integer(months.reduce((a, m) => a + m.days_recorded, 0))} days recorded</>} />
            <Stat label="Days left open" value={integer(openTotal)}
                  tone={openTotal > 0 ? 'bad' : 'good'}
                  sub={openTotal > 0
                    ? <>every month below is short by these days</>
                    : <>every recorded day is closed</>} />
          </div>

          {openTotal > 0 && (
            <div className="flex items-start gap-3 mb-4 px-4 py-3 rounded-xl border border-amber-400/30
                            bg-amber-500/10 text-amber-200 shadow-card">
              <span className="pill bg-amber-400/20 text-amber-200 shrink-0">{openTotal}</span>
              <span className="text-sm">
                <span className="font-semibold">Unclosed days.</span> A day with only an opening (or
                only a closing) reading adds zero kilometres, so the totals below are an under-count,
                not an over-count. Ask for the missing reading before paying against them.
              </span>
            </div>
          )}

          <div className="panel overflow-x-auto mb-6">
            <table className="w-full text-sm">
              <thead className="text-left border-b border-edge-soft">
                <tr>
                  <th className="px-3 py-2 font-medium text-xs">Month</th>
                  <th className="px-3 py-2 font-medium text-xs text-right">Kilometres</th>
                  <th className="px-3 py-2 font-medium text-xs text-right">Days recorded</th>
                  <th className="px-3 py-2 font-medium text-xs text-right">Days open</th>
                </tr>
              </thead>
              <tbody>
                {months.map((m) => (
                  <tr key={m.month} className="border-t border-edge-soft hover:bg-white/[0.02]">
                    <td className={cellL + ' font-medium text-slate-900'}>{m.month}</td>
                    <td className={cell + ' text-lg font-bold font-display text-slate-900'}>
                      {integer(m.km)}
                    </td>
                    <td className={cell}>{integer(m.days_recorded)}</td>
                    <td className={cell}>
                      {m.days_open > 0
                        ? <span className="pill bg-amber-500/15 text-amber-300"
                                title="These days have only one reading and add nothing to the total">
                            {m.days_open}
                          </span>
                        : <span className="text-slate-500">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <div className="flex items-center justify-between flex-wrap gap-3 mb-3">
        <h2 className="font-display font-semibold text-slate-900">
          Day by day
          {daily.data && (
            <span className="text-slate-500 font-sans text-sm font-normal">
              {' '}— {integer(daily.data.total_km)} km over {integer(daily.data.days_recorded)} closed day
              {daily.data.days_recorded === 1 ? '' : 's'}
              {daily.data.average_km !== null && <>, {daily.data.average_km} km a day</>}
            </span>
          )}
        </h2>
        <div className="flex gap-1">
          {[7, 30, 90].map((n) => (
            <Chip key={n} active={days === n} onClick={() => setDays(n)}>{n}d</Chip>
          ))}
        </div>
      </div>

      {daily.loading && !daily.data && <Spinner />}
      {daily.error && <p className="text-red-400">{daily.error}</p>}
      {daily.data && rows.length === 0 && (
        <Empty>No readings in the last {days} days. Days without a reading are absent rather than
          recorded as zero — a recruiter who did not ride did not record anything.</Empty>
      )}
      {rows.length > 0 && (
        <TableShell>
          <thead className="text-left border-b border-edge-soft">
            <tr>
              <th className="px-3 py-2 font-medium text-xs">Day</th>
              <th className="px-3 py-2 font-medium text-xs text-right">Start km</th>
              <th className="px-3 py-2 font-medium text-xs text-right">End km</th>
              <th className="px-3 py-2 font-medium text-xs text-right">Distance</th>
              <th className="px-3 py-2 font-medium text-xs">Evidence</th>
              <th className="px-3 py-2 font-medium text-xs">Note</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((d) => (
              <tr key={d.day} className={'border-t border-edge-soft hover:bg-white/[0.02]' +
                    (d.complete ? '' : ' bg-amber-500/[0.04]')}>
                <td className={cellL + ' font-medium text-slate-900'}>{d.day}</td>
                <td className={cell}>{d.start_km === null ? '—' : integer(d.start_km)}</td>
                <td className={cell}>{d.end_km === null ? '—' : integer(d.end_km)}</td>
                <td className={cell + (d.complete ? ' font-semibold text-slate-900' : ' text-amber-300')}>
                  {d.complete ? integer(d.distance_km ?? 0) + ' km' : 'open'}
                </td>
                <td className={cellL + ' text-xs'}>
                  <PhotoLink email={email} day={d.day} kind="start" present={d.has_start_photo} />
                  <PhotoLink email={email} day={d.day} kind="end" present={d.has_end_photo} />
                </td>
                <td className={cellL + ' text-xs text-slate-500'}>{d.note ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </TableShell>
      )}
    </>
  )
}

/** The dash photo behind one half of a day. A missing photo says so rather
 *  than opening onto a 404 the office would have to interpret. */
function PhotoLink({ email, day, kind, present }: {
  email: string; day: string; kind: 'start' | 'end'; present: boolean
}) {
  if (!present) {
    return <span className="text-slate-500 mr-3" title={`No ${kind}-of-day photo`}>no {kind}</span>
  }
  return (
    <a href={`/api/recruiters/${enc(email)}/shift/photo?kind=${kind}&day=${day}`}
       target="_blank" rel="noreferrer"
       className="text-brand-300 hover:underline mr-3"
       title={`Open the ${kind}-of-day dash photo for ${day}`}>
      📷 {kind}
    </a>
  )
}

// ── Profile ──────────────────────────────────────────────────────────────

function ProfileTab({ state }: { state: ReturnType<typeof useApi<Profile>> }) {
  const { data, loading, error } = state
  if (loading && !data) return <Spinner />
  if (error) return <p className="text-red-400">{error}</p>
  if (!data) return <Empty>No profile on file.</Empty>
  const p = data
  const empty = !p.full_name && !p.phone && !p.address && !p.account_no && !p.aadhaar_no && !p.pan_no

  return (
    <>
      {/* The server, not the console, decides how much of this travels. When it
          masks, the masked string IS the value we received — there is nothing
          held back in the browser and nothing to reveal. */}
      {p.masked && (
        <div className="flex items-start gap-3 mb-4 px-4 py-3 rounded-xl border border-edge
                        bg-white/[0.03] text-slate-600 text-sm">
          <span className="pill bg-white/[0.06] text-slate-500 shrink-0">masked</span>
          <span>
            The server sent these fields already shortened to their last few characters — enough to
            match a passbook, not enough to use. That is the whole value; nothing here is hidden
            behind a control.
          </span>
        </div>
      )}

      {empty ? (
        <Empty>This recruiter has not filled in their profile from the app yet.</Empty>
      ) : (
        <div className="grid md:grid-cols-2 gap-4">
          <section className="panel p-5">
            <h2 className="font-display font-semibold text-slate-900 mb-3">Person</h2>
            <dl className="grid grid-cols-[9rem_1fr] gap-y-2 text-sm">
              <Row label="Name" value={p.full_name ?? p.display_name} />
              <Row label="Phone" value={p.phone} />
              <Row label="Address" value={p.address} />
              <Row label="Zone" value={p.zone} />
            </dl>
          </section>

          <section className="panel p-5">
            <h2 className="font-display font-semibold text-slate-900 mb-3">Bank</h2>
            <dl className="grid grid-cols-[9rem_1fr] gap-y-2 text-sm">
              <Row label="Account name" value={p.account_name} />
              <Row label="Bank" value={p.bank_name} />
              <Row label="IFSC" value={p.ifsc} mono />
              <Row label="Account number" value={p.account_no} mono />
            </dl>
          </section>

          <section className="panel p-5">
            <h2 className="font-display font-semibold text-slate-900 mb-3">Identity</h2>
            <dl className="grid grid-cols-[9rem_1fr] gap-y-2 text-sm">
              <Row label="Aadhaar" value={p.aadhaar_no} mono />
              <Row label="PAN" value={p.pan_no} mono />
            </dl>
          </section>

          <section className="panel p-5">
            <h2 className="font-display font-semibold text-slate-900 mb-3">Account</h2>
            <dl className="grid grid-cols-[9rem_1fr] gap-y-2 text-sm">
              <Row label="Email" value={p.email} />
              <Row label="Role" value={p.role} />
              <Row label="Active" value={p.is_active ? 'yes' : 'no'} />
              <Row label="Last updated" value={p.updated_at} />
            </dl>
          </section>
        </div>
      )}
    </>
  )
}

function Row({ label, value, mono }: { label: string; value: string | null | undefined; mono?: boolean }) {
  return (
    <>
      <dt className="text-slate-500">{label}</dt>
      <dd className={'text-slate-900 break-words ' + (mono ? 'font-mono text-[13px]' : '')}>
        {value || <span className="text-slate-500">—</span>}
      </dd>
    </>
  )
}
