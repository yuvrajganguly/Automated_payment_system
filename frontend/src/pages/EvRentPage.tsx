import { Fragment, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { Spinner } from '../components/Spinner'
import { ColumnFilters, applyFilters } from '../components/TableFilters'
import { useUrlRecord, useUrlBool } from '../state/useUrlState'
import { usePersistedState } from '../state/usePersistedState'
import { SortableTh, useSort } from '../components/Sortable'

const fmt = (n: number) =>
  n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })

interface RiderLine {
  person_id: number
  rider_id: string | null
  display_name: string | null
  hub: string | null
  expected_rent: number
  collected_rent: number
  collected_current?: number
  prior_recovered: number
  rolled_forward: number
  arrears_rent: number
  future_arrears_recovered?: number     // backend already populates these
  future_xc_recovered?: number
  days_billed: number | null
  status: 'paid' | 'partial' | 'inactive' | 'recovered' | 'partial_recovered'
}

interface CycleRow {
  company: string
  cycle_start: string
  cycle_end: string
  expected_rent: number
  collected_rent: number
  collected_current?: number
  prior_recovered: number
  rolled_forward: number
  rolled_recovered_later: number
  rolled_forward_net: number
  arrears_rent: number
  arrears_recovered_later: number
  arrears_net: number
  rider_count: number
  legacy?: boolean
  by_rider: RiderLine[]
}

export function EvRentPage() {
  const [rows, setRows] = useState<CycleRow[]>([])
  const [companies, setCompanies] = useState<string[]>([])
  const [availableCompanies, setAvailableCompanies] = useState<string[]>([])
  const [filters, setFilters] = useUrlRecord('f')
  const [expanded, setExpanded] = usePersistedState<Record<string, boolean>>('evrent:expanded', {})
  const [latestOnly, setLatestOnly] = useUrlBool('latest', true)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.get<{ company_name: string }[]>('/companies')
      .then((cs) => setAvailableCompanies(cs.map((c) => c.company_name)))
      .catch(() => {})
  }, [])

  useEffect(() => {
    setBusy(true)
    const params = new URLSearchParams()
    params.set('latest_only', String(latestOnly))
    if (companies.length) params.set('companies', companies.join(','))
    api.get<CycleRow[]>('/ev-rent?' + params)
      .then(setRows)
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false))
  }, [latestOnly, companies])

  function toggleCompany(c: string) {
    setCompanies((cs) => cs.includes(c) ? cs.filter((x) => x !== c) : [...cs, c])
  }

  const filtered = useMemo(() => applyFilters(rows, filters), [rows, filters])
  const { sorted: visible, sortKey, sortDir, toggleSort } = useSort(filtered, { urlKey: 'sort' })

  // Use NET arrears / rolled — so the totals heal when cross-company
  // recoveries are detected. arrears_net = arrears − arrears_recovered_later
  // and rolled_forward_net = rolled_forward − rolled_recovered_later, both
  // bounded at zero in the backend.
  const totals = visible.reduce(
    (a, r) => ({
      expected: a.expected + r.expected_rent,
      collected: a.collected + r.collected_rent,
      prior: a.prior + (r.prior_recovered ?? 0),
      rolled: a.rolled + (r.rolled_forward_net ?? r.rolled_forward),
      arrears: a.arrears + (r.arrears_net ?? r.arrears_rent),
      arrears_gross: a.arrears_gross + r.arrears_rent,
      rolled_gross: a.rolled_gross + r.rolled_forward,
    }),
    { expected: 0, collected: 0, prior: 0, rolled: 0, arrears: 0,
      arrears_gross: 0, rolled_gross: 0 },
  )

  return (
    <div className="max-w-7xl mx-auto">
      <h1 className="text-2xl font-bold mb-1">EV Rent Details</h1>
      <p className="text-slate-500 text-sm mb-6">
        Per-cycle, per-company breakdown of what the engine expected to collect
        versus what it actually billed. Missed rent went into EV-arrears and
        will be clawed back automatically next time the rider gets a payout.
        Rent is logged at exactly one company per person per cycle, so people
        on multiple companies are not double-counted.
      </p>

      <div className="flex flex-wrap items-center gap-2 mb-4">
        <span className="text-xs text-slate-500 mr-1">Show:</span>
        <button onClick={() => setLatestOnly(true)}
                className={'text-xs px-3 py-1 rounded ' +
                  (latestOnly ? 'bg-brand text-white' : 'bg-slate-200 hover:bg-slate-300')}>
          Latest per company
        </button>
        <button onClick={() => setLatestOnly(false)}
                className={'text-xs px-3 py-1 rounded ' +
                  (!latestOnly ? 'bg-brand text-white' : 'bg-slate-200 hover:bg-slate-300')}>
          All cycles
        </button>
        <span className="text-xs text-slate-500 ml-3 mr-1">Companies:</span>
        <button onClick={() => setCompanies([])}
                className={'text-xs px-2 py-1 rounded ' +
                  (companies.length === 0
                    ? 'bg-brand text-white'
                    : 'bg-slate-200 hover:bg-slate-300')}>
          All
        </button>
        {availableCompanies.map((c) => (
          <button key={c} onClick={() => toggleCompany(c)}
                  className={'text-xs px-2 py-1 rounded ' +
                    (companies.includes(c)
                      ? 'bg-brand text-white'
                      : 'bg-slate-200 hover:bg-slate-300')}>
            {c}
          </button>
        ))}
      </div>

      <ColumnFilters
        rows={rows}
        columns={[
          { key: 'company',    label: 'Company' },
          { key: 'cycle_end',  label: 'Cycle (end)' },
        ]}
        filters={filters}
        onChange={setFilters}
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        <Stat label="Expected rent" value={fmt(totals.expected)} tone="expected" />
        <Stat label="Collected from payout" value={fmt(totals.collected)} tone="charged" />
        <Stat label="Rolled to next cycle (net)"
              value={fmt(totals.rolled)}
              tone="rolled"
              sub={totals.rolled_gross > totals.rolled
                ? `Gross ${fmt(totals.rolled_gross)} − recovered later ${fmt(totals.rolled_gross - totals.rolled)}`
                : undefined} />
        <Stat label="Arrears (net)"
              value={fmt(totals.arrears)}
              tone="missed"
              sub={totals.arrears_gross > totals.arrears
                ? `Gross ${fmt(totals.arrears_gross)} − recovered later ${fmt(totals.arrears_gross - totals.arrears)}`
                : undefined} />
      </div>

      {busy && <Spinner />}
      {error && <p className="text-red-400 text-sm mb-3">{error}</p>}
      <p className="text-xs text-slate-500 mb-3">Showing {visible.length} of {rows.length} cycles.</p>

      <div className="panel overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-100 text-left">
            <tr>
              <Th>{''}</Th>
              <SortableTh tag="company" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Company</SortableTh>
              <SortableTh tag="cycle_start" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Cycle start</SortableTh>
              <SortableTh tag="cycle_end" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Cycle end</SortableTh>
              <SortableTh tag="rider_count" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Riders</SortableTh>
              <SortableTh tag="expected_rent" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Expected</SortableTh>
              <SortableTh tag="collected_rent" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Collected</SortableTh>
              <SortableTh tag="prior_recovered" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>incl. prior</SortableTh>
              <SortableTh tag="rolled_forward" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Rolled fwd</SortableTh>
              <SortableTh tag="arrears_rent" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Arrears</SortableTh>
              <Th>{''}</Th>
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => {
              const key = `${r.company}|${r.cycle_end}`
              const isOpen = expanded[key]
              const currentCollected = r.collected_current
                ?? (r.collected_rent - (r.prior_recovered ?? 0))
              const collectedPct = r.expected_rent === 0 ? 0
                                  : (currentCollected / r.expected_rent) * 100
              return (
                <Fragment key={key}>
                  <tr className="border-t hover:bg-slate-50 cursor-pointer"
                      onClick={() => setExpanded({ ...expanded, [key]: !isOpen })}>
                    <Td className="text-slate-400">{isOpen ? '▼' : '▶'}</Td>
                    <Td className="font-medium">
                      {r.company}
                      {r.legacy && (
                        <span title="Cycle processed before the partial-collection tracker existed. Numbers below are estimates."
                              className="ml-1 text-[10px] px-1 py-0.5 rounded bg-slate-200 text-slate-700">
                          legacy
                        </span>
                      )}
                    </Td>
                    <Td>{r.cycle_start}</Td>
                    <Td>{r.cycle_end}</Td>
                    <Td right>{r.rider_count}</Td>
                    <Td right>{fmt(r.expected_rent)}</Td>
                    <Td right className="text-emerald-300 font-medium">{fmt(r.collected_rent)}</Td>
                    <Td right className={(r.prior_recovered ?? 0) > 0 ? 'text-emerald-400 italic' : 'text-slate-400'}
                        title="Of the collected total, this much was recovery of prior-cycle pending or arrears (not new rent owed this cycle).">
                      {fmt(r.prior_recovered ?? 0)}
                    </Td>
                    <Td right className={r.rolled_forward > 0 ? 'text-amber-300 font-semibold' : 'text-slate-400'}
                        title={(r.rolled_recovered_later ?? 0) > 0
                          ? `${fmt(r.rolled_recovered_later)} of this was recovered later — net ${fmt(r.rolled_forward_net)}`
                          : undefined}>
                      {(r.rolled_recovered_later ?? 0) > 0 ? (
                        <>
                          <span className="line-through text-slate-400 mr-1">{fmt(r.rolled_forward)}</span>
                          <span className="text-emerald-300">{fmt(r.rolled_forward_net)}</span>
                        </>
                      ) : fmt(r.rolled_forward)}
                    </Td>
                    <Td right className={r.arrears_rent > 0 ? 'text-red-300 font-semibold' : 'text-slate-400'}
                        title={(r.arrears_recovered_later ?? 0) > 0
                          ? `${fmt(r.arrears_recovered_later)} of this was recovered later — net ${fmt(r.arrears_net)}`
                          : undefined}>
                      {(r.arrears_recovered_later ?? 0) > 0 ? (
                        <>
                          <span className="line-through text-slate-400 mr-1">{fmt(r.arrears_rent)}</span>
                          <span className="text-emerald-300">{fmt(r.arrears_net)}</span>
                        </>
                      ) : fmt(r.arrears_rent)}
                    </Td>
                    <Td>
                      <span className="text-xs text-slate-500">{collectedPct.toFixed(0)}%</span>
                    </Td>
                  </tr>
                  {isOpen && (
                    <tr key={key + ':rider'}>
                      <td colSpan={10} className="bg-slate-50 p-3">
                        <RiderBreakdown rows={r.by_rider} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
        {visible.length === 0 && !busy && (
          <p className="p-6 text-center text-slate-500 text-sm">
            No EV-rent activity yet — run a cycle to see numbers here.
          </p>
        )}
      </div>
    </div>
  )
}

function RiderBreakdown({ rows }: { rows: RiderLine[] }) {
  if (rows.length === 0) return <p className="text-xs text-slate-500">No riders billed.</p>
  return (
    <table className="w-full text-xs">
      <thead className="bg-panel text-left">
        <tr>
          <th className="px-2 py-1">Person</th>
          <th className="px-2 py-1">Rider ID</th>
          <th className="px-2 py-1">Name</th>
          <th className="px-2 py-1">Hub</th>
          <th className="px-2 py-1">Days</th>
          <th className="px-2 py-1 text-right">Expected</th>
          <th className="px-2 py-1 text-right">Collected</th>
          <th className="px-2 py-1 text-right" title="Of the collected total, how much was prior-cycle recovery (XC pending or arrears).">incl. prior</th>
          <th className="px-2 py-1 text-right">Rolled fwd</th>
          <th className="px-2 py-1 text-right">To arrears</th>
          <th className="px-2 py-1">Status</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.person_id + ':' + (r.rider_id ?? '')} className="border-t">
            <td className="px-2 py-1">
              <Link to={'/persons/' + r.person_id} className="text-brand underline">#{r.person_id}</Link>
            </td>
            <td className="px-2 py-1">{r.rider_id ?? '-'}</td>
            <td className="px-2 py-1">{r.display_name}</td>
            <td className="px-2 py-1">{r.hub ?? '-'}</td>
            <td className="px-2 py-1">{r.days_billed ?? '-'}</td>
            <td className="px-2 py-1 text-right">{fmt(r.expected_rent)}</td>
            <td className="px-2 py-1 text-right text-emerald-300">{fmt(r.collected_rent)}</td>
            <td className={'px-2 py-1 text-right italic ' + ((r.prior_recovered ?? 0) > 0 ? 'text-emerald-400' : 'text-slate-300')}>
              {fmt(r.prior_recovered ?? 0)}
            </td>
            <td className={'px-2 py-1 text-right ' + (r.rolled_forward > 0 ? 'text-amber-300 font-medium' : '')}
                title={(r.future_xc_recovered ?? 0) > 0
                  ? `${fmt(r.future_xc_recovered ?? 0)} of this was recovered at a later cycle`
                  : undefined}>
              {(r.future_xc_recovered ?? 0) > 0 ? (
                <>
                  <span className="line-through text-slate-400 mr-1">{fmt(r.rolled_forward)}</span>
                  <span className="text-emerald-300">
                    {fmt(Math.max(0, r.rolled_forward - (r.future_xc_recovered ?? 0)))}
                  </span>
                </>
              ) : fmt(r.rolled_forward)}
            </td>
            <td className={'px-2 py-1 text-right ' + (r.arrears_rent > 0 ? 'text-red-300 font-medium' : '')}
                title={(r.future_arrears_recovered ?? 0) > 0
                  ? `${fmt(r.future_arrears_recovered ?? 0)} of this was recovered at a later cycle`
                  : undefined}>
              {(r.future_arrears_recovered ?? 0) > 0 ? (
                <>
                  <span className="line-through text-slate-400 mr-1">{fmt(r.arrears_rent)}</span>
                  <span className="text-emerald-300">
                    {fmt(Math.max(0, r.arrears_rent - (r.future_arrears_recovered ?? 0)))}
                  </span>
                </>
              ) : fmt(r.arrears_rent)}
            </td>
            <td className="px-2 py-1">
              <span className={'text-xs px-1.5 py-0.5 rounded ' +
                (r.status === 'paid'               ? 'bg-emerald-500/15'
                 : r.status === 'recovered'         ? 'bg-emerald-500/20 text-emerald-200'
                 : r.status === 'partial_recovered' ? 'bg-teal-500/15 text-teal-200'
                 : r.status === 'inactive'          ? 'bg-red-500/15'
                 :                                    'bg-amber-500/15')}
                title={r.status === 'recovered'
                       ? 'Originally inactive/partial here; rent fully recovered at a later cycle.'
                       : r.status === 'partial_recovered'
                       ? 'Some of the shortfall was recovered later, but not all.'
                       : undefined}>
                {r.status === 'partial_recovered' ? 'partly recovered' : r.status}
              </span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Stat({ label, value, tone, sub }:
  { label: string; value: string; sub?: string
    tone: 'expected' | 'charged' | 'rolled' | 'missed' }) {
  const ring = tone === 'missed'   ? 'border-l-[3px] border-l-red-400'
             : tone === 'rolled'   ? 'border-l-[3px] border-l-amber-400'
             : tone === 'charged'  ? 'border-l-[3px] border-l-emerald-400'
             :                       'border-l-[3px] border-l-slate-400'
  return <div className={'panel p-3 ' + ring}>
    <p className="text-xs text-slate-500">{label}</p>
    <p className="text-lg font-bold">{value}</p>
    {sub && <p className="text-[10px] text-emerald-300 mt-0.5">{sub}</p>}
  </div>
}
function Th({ children }: { children: React.ReactNode }) {
  return <th className="px-3 py-2 font-medium text-xs">{children}</th>
}
function Td({ children, right, className = '', title }:
  { children: React.ReactNode; right?: boolean; className?: string; title?: string }) {
  return <td className={'px-3 py-2 ' + (right ? 'text-right ' : '') + className} title={title}>{children}</td>
}
