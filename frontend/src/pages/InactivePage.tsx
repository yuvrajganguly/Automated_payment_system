import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { Spinner } from '../components/Spinner'
import { ColumnFilters, applyFilters } from '../components/TableFilters'
import { SortableTh, useSort } from '../components/Sortable'

const fmt = (n: number) =>
  n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })

interface InactiveRow {
  person_id: number
  display_name: string
  ev_id: string
  handover_date: string | null
  rent_charged_through: string | null
  last_seen_cycle: string | null
  current_balance: number
  arrears_outstanding: number
  total_missed: number
  companies: string
  hubs: string
  reason: string
}

export function InactivePage() {
  const [rows, setRows] = useState<InactiveRow[]>([])
  const [days, setDays] = useState(14)
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setBusy(true); setError(null)
    api.get<InactiveRow[]>(`/inactive?days=${days}`)
      .then(setRows)
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false))
  }, [days])

  const filtered = useMemo(() => applyFilters(rows, filters), [rows, filters])
  const { sorted: visible, sortKey, sortDir, toggleSort } = useSort(filtered)

  const totals = visible.reduce(
    (a, r) => ({
      dues: a.dues + Math.max(0, -r.current_balance),
      arrears: a.arrears + r.arrears_outstanding,
    }),
    { dues: 0, arrears: 0 },
  )

  return (
    <div className="max-w-7xl mx-auto">
      <h1 className="text-2xl font-bold mb-1">Inactive Riders</h1>
      <p className="text-slate-500 text-sm mb-6">
        Riders with an open EV who haven't been processed recently, or who carry outstanding dues or EV-rent arrears.
        Per-cycle inactive lists in the workbook are scoped to that cycle's company; this view aggregates across all.
      </p>

      <div className="bg-white rounded-lg shadow p-4 mb-4 flex flex-wrap gap-4 items-end">
        <div>
          <label className="block text-xs font-medium mb-1">Considered inactive after</label>
          <select value={days} onChange={(e) => setDays(parseInt(e.target.value))}
                  className="border rounded px-3 py-2 text-sm">
            <option value={7}>7 days</option>
            <option value={14}>14 days</option>
            <option value={30}>30 days</option>
            <option value={60}>60 days</option>
            <option value={365}>1 year</option>
          </select>
        </div>
        {busy && <Spinner />}
      </div>
      <ColumnFilters
        rows={rows}
        columns={[
          { key: 'companies', label: 'Company' },
          { key: 'hubs',      label: 'Hub' },
        ]}
        filters={filters}
        onChange={setFilters}
      />

      <div className="grid grid-cols-3 gap-4 mb-4">
        <Stat label="Inactive riders" value={visible.length.toString()} />
        <Stat label="Outstanding dues" value={fmt(totals.dues)} />
        <Stat label="EV-rent arrears" value={fmt(totals.arrears)} bad />
      </div>

      {error && <p className="text-red-600 text-sm mb-3">{error}</p>}

      <div className="bg-white rounded-lg shadow overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-100 text-left">
            <tr>
              <SortableTh tag="person_id" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Person</SortableTh>
              <SortableTh tag="display_name" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Name</SortableTh>
              <SortableTh tag="companies" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Companies</SortableTh>
              <SortableTh tag="hubs" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Hub</SortableTh>
              <SortableTh tag="ev_id" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>EV</SortableTh>
              <SortableTh tag="handover_date" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Handover</SortableTh>
              <SortableTh tag="rent_charged_through" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Rent through</SortableTh>
              <SortableTh tag="last_seen_cycle" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Last seen</SortableTh>
              <SortableTh tag="current_balance" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Dues</SortableTh>
              <SortableTh tag="arrears_outstanding" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>EV Arrears</SortableTh>
              <Th>Reason</Th>
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
                <Td className="text-xs">{r.handover_date ?? '-'}</Td>
                <Td className="text-xs">{r.rent_charged_through ?? '-'}</Td>
                <Td className="text-xs">{r.last_seen_cycle ?? 'never'}</Td>
                <Td right className={r.current_balance < 0 ? 'text-red-700 font-medium' : ''}>
                  {fmt(Math.max(0, -r.current_balance))}
                </Td>
                <Td right className={r.arrears_outstanding > 0 ? 'text-red-700 font-medium' : ''}>
                  {fmt(r.arrears_outstanding)}
                </Td>
                <Td className="text-xs">{r.reason}</Td>
              </tr>
            ))}
          </tbody>
        </table>
        {visible.length === 0 && !busy && (
          <p className="p-6 text-center text-slate-500 text-sm">
            No inactive riders right now.
          </p>
        )}
      </div>
    </div>
  )
}

function Stat({ label, value, bad }: { label: string; value: string; bad?: boolean }) {
  return <div className="bg-white rounded-lg shadow p-3">
    <p className="text-xs text-slate-500">{label}</p>
    <p className={'text-lg font-semibold ' + (bad ? 'text-red-600' : '')}>{value}</p>
  </div>
}
function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return <th className={'px-3 py-2 font-medium text-xs ' + (right ? 'text-right' : '')}>{children}</th>
}
function Td({ children, right, className = '' }: { children: React.ReactNode; right?: boolean; className?: string }) {
  return <td className={'px-3 py-2 ' + (right ? 'text-right ' : '') + className}>{children}</td>
}
