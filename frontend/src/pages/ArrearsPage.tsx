import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { Spinner } from '../components/Spinner'
import { ColumnFilters, applyFilters } from '../components/TableFilters'
import { useUrlRecord, useUrlString } from '../state/useUrlState'
import { ExportButton } from '../components/ExportButton'
import { SortableTh, useSort } from '../components/Sortable'

const fmt = (n: number) =>
  n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })

interface ArrearsRow {
  person_id: number
  display_name: string
  ev_id: string | null
  model: string | null
  total_missed: number
  total_recovered: number
  outstanding: number          // EV-rent outstanding
  cod_missed: number
  cod_recovered: number
  cod_outstanding: number
  dues_outstanding: number     // general carryforward (positive number)
  total_dues?: number          // EV arrears net of any credit balance (>0 owes)
  companies: string | null
  hubs: string | null
  last_updated: string | null
  /** EV arrears but the EV was returned — kept silently; payouts are HELD. */
  dormant?: boolean | number
}

type Bucket = 'all' | 'ev' | 'dues'

export function ArrearsPage() {
  const [rows, setRows] = useState<ArrearsRow[]>([])
  const [filters, setFilters] = useUrlRecord('f')
  const [bucket, setBucket] = useUrlString('bucket', 'all') as [Bucket, (v: Bucket) => void]
  const [dormantParam, setDormantParam] = useUrlString('dormant', '0')
  const showDormant = dormantParam === '1'
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setBusy(true)
    api.get<ArrearsRow[]>('/arrears', { query: { include_dormant: showDormant } })
      .then(setRows)
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false))
  }, [showDormant])

  const scoped = useMemo(() => {
    switch (bucket) {
      case 'ev':   return rows.filter((r) => r.outstanding > 0 || r.total_missed > 0)
      case 'dues': return rows.filter((r) => r.dues_outstanding > 0)
      default:     return rows
    }
  }, [rows, bucket])
  const filtered = useMemo(() => applyFilters(scoped, filters), [scoped, filters])
  const { sorted: visible, sortKey, sortDir, toggleSort } = useSort(filtered, { urlKey: 'sort' })

  const totals = visible.reduce(
    (a, r) => ({
      ev_outstanding:  a.ev_outstanding  + r.outstanding,
      dues:            a.dues            + r.dues_outstanding,
    }),
    { ev_outstanding: 0, dues: 0 },
  )

  return (
    <div className="max-w-7xl mx-auto">
      <div className="flex items-start justify-between gap-3 mb-1">
        <h1 className="text-2xl font-bold">Arrears</h1>
        <ExportButton path="/arrears/export" name="arrears.xlsx" ids={visible.map((r) => r.person_id)} />
      </div>
      <p className="text-slate-500 text-sm mb-6">
        Two buckets: EV-rent missed while a rider was absent, and general dues
        (carryforward from prior cycles). Each bucket rolls forward and is
        clawed back automatically from future payouts. COD-pending lives on
        its own page.
      </p>

      <div className="flex items-center gap-2 mb-4">
        <span className="text-xs text-slate-500 mr-1">Show:</span>
        {(['all', 'ev', 'dues'] as Bucket[]).map((b) => (
          <button key={b} onClick={() => setBucket(b)}
                  className={'text-xs px-3 py-1 rounded ' +
                    (bucket === b ? 'bg-brand text-white' : 'bg-slate-200 hover:bg-slate-300')}>
            {b === 'all' ? 'All' : b === 'ev' ? 'EV-rent only' : 'Dues only'}
          </button>
        ))}
        <label className="ml-4 inline-flex items-center gap-1.5 text-xs text-slate-600 cursor-pointer">
          <input type="checkbox" checked={showDormant}
                 onChange={(e) => setDormantParam(e.target.checked ? '1' : '0')} />
          Show dormant (EV returned, debt kept silently)
        </label>
      </div>

      <ColumnFilters
        rows={scoped}
        columns={[
          { key: 'companies', label: 'Company' },
          { key: 'hubs',      label: 'Hub' },
          { key: 'model',     label: 'EV Model' },
        ]}
        filters={filters}
        onChange={setFilters}
      />

      {busy && <Spinner />}
      {error && <p className="text-red-600 text-sm mb-3">{error}</p>}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
        <Stat label="EV-rent outstanding" value={fmt(totals.ev_outstanding)} tone="ev" />
        <Stat label="Dues (carryforward)" value={fmt(totals.dues)} tone="dues" />
        <Stat label="Total outstanding"
              value={fmt(totals.ev_outstanding + totals.dues)} tone="total" />
      </div>
      <p className="text-xs text-slate-500 mb-3">Showing {visible.length} of {rows.length} riders.</p>

      <div className="bg-white rounded-xl border border-slate-200/80 shadow-card overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-100 text-left">
            <tr>
              <SortableTh tag="person_id" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Person</SortableTh>
              <SortableTh tag="display_name" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Name</SortableTh>
              <SortableTh tag="companies" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Companies</SortableTh>
              <SortableTh tag="hubs" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Hub</SortableTh>
              <SortableTh tag="ev_id" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>EV</SortableTh>
              <SortableTh tag="model" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Model</SortableTh>
              <SortableTh tag="outstanding" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>EV Outstanding</SortableTh>
              <SortableTh tag="dues_outstanding" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Dues (Carryfwd)</SortableTh>
              <SortableTh tag="total_dues" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Total Dues</SortableTh>
              <SortableTh tag="last_updated" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Last Updated</SortableTh>
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => (
              <tr key={r.person_id} className="border-t hover:bg-slate-50">
                <Td><Link to={'/persons/' + r.person_id} className="text-brand underline">
                  #{r.person_id}
                </Link></Td>
                <Td>
                  {r.display_name}
                  {!!r.dormant && (
                    <span className="ml-2 text-[10px] uppercase tracking-wide bg-slate-200 text-slate-600 px-1.5 py-0.5 rounded"
                          title="EV returned with arrears still owed. Hidden from the active view; any future payout is HELD for manual resolution.">
                      Dormant
                    </span>
                  )}
                </Td>
                <Td className="text-xs">{r.companies || '-'}</Td>
                <Td className="text-xs">{r.hubs || '-'}</Td>
                <Td>{r.ev_id ?? '-'}</Td>
                <Td>{r.model ?? '-'}</Td>
                <Td right className={r.outstanding > 0 ? 'font-semibold text-amber-700' : 'text-slate-400'}>
                  {fmt(r.outstanding)}
                </Td>
                <Td right className={r.dues_outstanding > 0 ? 'font-semibold text-blue-700' : 'text-slate-400'}>
                  {fmt(r.dues_outstanding)}
                </Td>
                <Td right className={(r.total_dues ?? (r.outstanding + r.dues_outstanding)) > 0 ? 'font-bold text-rose-700' : (r.total_dues ?? (r.outstanding + r.dues_outstanding)) < 0 ? 'font-semibold text-emerald-700' : 'text-slate-400'}>
                  {fmt(r.total_dues ?? (r.outstanding + r.dues_outstanding))}
                </Td>
                <Td className="text-xs">{r.last_updated ?? ''}</Td>
              </tr>
            ))}
          </tbody>
        </table>
        {visible.length === 0 && !busy &&
          <p className="p-6 text-center text-slate-500 text-sm">Nothing owed in this bucket. Nice.</p>}
      </div>
    </div>
  )
}

function Stat({ label, value, tone }:
  { label: string; value: string; tone: 'ev' | 'dues' | 'total' }) {
  const ring = tone === 'ev'    ? 'border-l-4 border-amber-400'
             : tone === 'total' ? 'border-l-4 border-emerald-500'
             :                    'border-l-4 border-blue-400'
  return <div className={'bg-white rounded-xl border border-slate-200/80 shadow-card p-3 ' + ring}>
    <p className="text-xs text-slate-500">{label}</p>
    <p className="text-lg font-bold">{value}</p>
  </div>
}
function Td({ children, right, className = '' }:
  { children: React.ReactNode; right?: boolean; className?: string }) {
  return <td className={'px-3 py-2 ' + (right ? 'text-right ' : '') + className}>{children}</td>
}
