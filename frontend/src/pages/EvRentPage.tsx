import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { Spinner } from '../components/Spinner'
import { ColumnFilters, applyFilters } from '../components/TableFilters'
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
  prior_recovered: number
  rolled_forward: number
  arrears_rent: number
  days_billed: number | null
  status: 'paid' | 'partial' | 'inactive' | 'recovered' | 'partial_recovered'
}

interface CycleRow {
  company: string
  cycle_start: string
  cycle_end: string
  expected_rent: number
  collected_rent: number
  prior_recovered: number
  rolled_forward: number
  arrears_rent: number
  rider_count: number
  legacy?: boolean
  by_rider: RiderLine[]
}

export function EvRentPage() {
  const [rows, setRows] = useState<CycleRow[]>([])
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [latestOnly, setLatestOnly] = useState(true)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setBusy(true)
    api.get<CycleRow[]>('/ev-rent?latest_only=' + latestOnly)
      .then(setRows)
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false))
  }, [latestOnly])

  const filtered = useMemo(() => applyFilters(rows, filters), [rows, filters])
  const { sorted: visible, sortKey, sortDir, toggleSort } = useSort(filtered)

  const totals = visible.reduce(
    (a, r) => ({
      expected: a.expected + r.expected_rent,
      collected: a.collected + r.collected_rent,
      prior: a.prior + (r.prior_recovered ?? 0),
      rolled: a.rolled + r.rolled_forward,
      arrears: a.arrears + r.arrears_rent,
    }),
    { expected: 0, collected: 0, prior: 0, rolled: 0, arrears: 0 },
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

      <div className="flex items-center gap-2 mb-4">
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
        <Stat label="Rolled to next cycle" value={fmt(totals.rolled)} tone="rolled" />
        <Stat label="Arrears (inactive riders)" value={fmt(totals.arrears)} tone="missed" />
      </div>

      {busy && <Spinner />}
      {error && <p className="text-red-600 text-sm mb-3">{error}</p>}
      <p className="text-xs text-slate-500 mb-3">Showing {visible.length} of {rows.length} cycles.</p>

      <div className="bg-white rounded-lg shadow overflow-x-auto">
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
              const collectedPct = r.expected_rent === 0 ? 0
                                  : (r.collected_rent / r.expected_rent) * 100
              return (
                <>
                  <tr key={key} className="border-t hover:bg-slate-50 cursor-pointer"
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
                    <Td right className="text-emerald-700 font-medium">{fmt(r.collected_rent)}</Td>
                    <Td right className={(r.prior_recovered ?? 0) > 0 ? 'text-emerald-600 italic' : 'text-slate-400'}
                        title="Of the collected total, this much was recovery of prior-cycle pending or arrears (not new rent owed this cycle).">
                      {fmt(r.prior_recovered ?? 0)}
                    </Td>
                    <Td right className={r.rolled_forward > 0 ? 'text-amber-700 font-semibold' : 'text-slate-400'}>
                      {fmt(r.rolled_forward)}
                    </Td>
                    <Td right className={r.arrears_rent > 0 ? 'text-red-700 font-semibold' : 'text-slate-400'}>
                      {fmt(r.arrears_rent)}
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
                </>
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
      <thead className="bg-white text-left">
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
            <td className="px-2 py-1 text-right text-emerald-700">{fmt(r.collected_rent)}</td>
            <td className={'px-2 py-1 text-right italic ' + ((r.prior_recovered ?? 0) > 0 ? 'text-emerald-600' : 'text-slate-300')}>
              {fmt(r.prior_recovered ?? 0)}
            </td>
            <td className={'px-2 py-1 text-right ' + (r.rolled_forward > 0 ? 'text-amber-700 font-medium' : '')}>
              {fmt(r.rolled_forward)}
            </td>
            <td className={'px-2 py-1 text-right ' + (r.arrears_rent > 0 ? 'text-red-700 font-medium' : '')}>
              {fmt(r.arrears_rent)}
            </td>
            <td className="px-2 py-1">
              <span className={'text-xs px-1.5 py-0.5 rounded ' +
                (r.status === 'paid'               ? 'bg-green-100'
                 : r.status === 'recovered'         ? 'bg-emerald-200 text-emerald-900'
                 : r.status === 'partial_recovered' ? 'bg-teal-100 text-teal-900'
                 : r.status === 'inactive'          ? 'bg-red-100'
                 :                                    'bg-amber-100')}
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

function Stat({ label, value, tone }:
  { label: string; value: string; tone: 'expected' | 'charged' | 'rolled' | 'missed' }) {
  const ring = tone === 'missed'   ? 'border-l-4 border-red-400'
             : tone === 'rolled'   ? 'border-l-4 border-amber-400'
             : tone === 'charged'  ? 'border-l-4 border-emerald-400'
             :                       'border-l-4 border-slate-400'
  return <div className={'bg-white rounded-lg shadow p-3 ' + ring}>
    <p className="text-xs text-slate-500">{label}</p>
    <p className="text-lg font-bold">{value}</p>
  </div>
}
function Th({ children }: { children: React.ReactNode }) {
  return <th className="px-3 py-2 font-medium text-xs">{children}</th>
}
function Td({ children, right, className = '', title }:
  { children: React.ReactNode; right?: boolean; className?: string; title?: string }) {
  return <td className={'px-3 py-2 ' + (right ? 'text-right ' : '') + className} title={title}>{children}</td>
}
