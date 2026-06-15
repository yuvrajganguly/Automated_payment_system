import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { Spinner } from '../components/Spinner'
import { ColumnFilters, applyFilters } from '../components/TableFilters'
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
  companies: string | null
  hubs: string | null
  last_updated: string | null
}

type Bucket = 'all' | 'ev' | 'cod' | 'dues'

export function ArrearsPage() {
  const [rows, setRows] = useState<ArrearsRow[]>([])
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [bucket, setBucket] = useState<Bucket>('all')
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.get<ArrearsRow[]>('/arrears')
      .then(setRows)
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false))
  }, [])

  const scoped = useMemo(() => {
    switch (bucket) {
      case 'ev':   return rows.filter((r) => r.outstanding > 0 || r.total_missed > 0)
      case 'cod':  return rows.filter((r) => r.cod_outstanding > 0 || r.cod_missed > 0)
      case 'dues': return rows.filter((r) => r.dues_outstanding > 0)
      default:     return rows
    }
  }, [rows, bucket])
  const filtered = useMemo(() => applyFilters(scoped, filters), [scoped, filters])
  const { sorted: visible, sortKey, sortDir, toggleSort } = useSort(filtered)

  const totals = visible.reduce(
    (a, r) => ({
      ev_outstanding:  a.ev_outstanding  + r.outstanding,
      cod_outstanding: a.cod_outstanding + r.cod_outstanding,
      dues:            a.dues            + r.dues_outstanding,
    }),
    { ev_outstanding: 0, cod_outstanding: 0, dues: 0 },
  )

  return (
    <div className="max-w-7xl mx-auto">
      <h1 className="text-2xl font-bold mb-1">Arrears</h1>
      <p className="text-slate-500 text-sm mb-6">
        Three buckets: EV-rent missed while a rider was absent, COD-pending the
        company couldn't clear, and general dues (carryforward from prior
        cycles). Each bucket rolls forward and is clawed back automatically
        from future payouts.
      </p>

      <div className="flex items-center gap-2 mb-4">
        <span className="text-xs text-slate-500 mr-1">Show:</span>
        {(['all', 'ev', 'cod', 'dues'] as Bucket[]).map((b) => (
          <button key={b} onClick={() => setBucket(b)}
                  className={'text-xs px-3 py-1 rounded ' +
                    (bucket === b ? 'bg-brand text-white' : 'bg-slate-200 hover:bg-slate-300')}>
            {b === 'all' ? 'All' : b === 'ev' ? 'EV-rent only' : b === 'cod' ? 'COD only' : 'Dues only'}
          </button>
        ))}
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
        <Stat label="COD outstanding"     value={fmt(totals.cod_outstanding)} tone="cod" />
        <Stat label="Dues (carryforward)" value={fmt(totals.dues)} tone="dues" />
      </div>
      <p className="text-xs text-slate-500 mb-3">Showing {visible.length} of {rows.length} riders.</p>

      <div className="bg-white rounded-lg shadow overflow-x-auto">
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
              <SortableTh tag="cod_outstanding" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>COD Outstanding</SortableTh>
              <SortableTh tag="dues_outstanding" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Dues (Carryfwd)</SortableTh>
              <SortableTh tag="last_updated" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Last Updated</SortableTh>
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => (
              <tr key={r.person_id} className="border-t hover:bg-slate-50">
                <Td><Link to={'/persons/' + r.person_id} className="text-brand underline">
                  #{r.person_id}
                </Link></Td>
                <Td>{r.display_name}</Td>
                <Td className="text-xs">{r.companies || '-'}</Td>
                <Td className="text-xs">{r.hubs || '-'}</Td>
                <Td>{r.ev_id ?? '-'}</Td>
                <Td>{r.model ?? '-'}</Td>
                <Td right className={r.outstanding > 0 ? 'font-semibold text-amber-700' : 'text-slate-400'}>
                  {fmt(r.outstanding)}
                </Td>
                <Td right className={r.cod_outstanding > 0 ? 'font-semibold text-red-700' : 'text-slate-400'}>
                  {fmt(r.cod_outstanding)}
                </Td>
                <Td right className={r.dues_outstanding > 0 ? 'font-semibold text-blue-700' : 'text-slate-400'}>
                  {fmt(r.dues_outstanding)}
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

function Stat({ label, value, tone }: { label: string; value: string; tone: 'ev' | 'cod' | 'dues' }) {
  const ring = tone === 'cod' ? 'border-l-4 border-red-400'
             : tone === 'ev'  ? 'border-l-4 border-amber-400'
             :                  'border-l-4 border-blue-400'
  return <div className={'bg-white rounded-lg shadow p-3 ' + ring}>
    <p className="text-xs text-slate-500">{label}</p>
    <p className="text-lg font-bold">{value}</p>
  </div>
}
function Td({ children, right, className = '' }:
  { children: React.ReactNode; right?: boolean; className?: string }) {
  return <td className={'px-3 py-2 ' + (right ? 'text-right ' : '') + className}>{children}</td>
}
