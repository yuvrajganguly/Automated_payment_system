import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Spinner } from '../components/Spinner'
import { ColumnFilters, applyFilters } from '../components/TableFilters'
import { useUrlRecord } from '../state/useUrlState'
import { SortableTh, useSort } from '../components/Sortable'

const fmt = (n: number | null | undefined) =>
  (n ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })

interface CompanyRun {
  company: string
  cycle_start: string
  cycle_end: string
  processed_at: string | null
  riders: number
}

interface ActiveRider {
  company: string
  cycle_start: string
  cycle_end: string
  rider_id: string
  person_id: number | null
  name: string
  hub: string | null
  mob_no: string | null
  ev_id: string | null
  id_active: boolean | null
  payout?: number
}

interface ActiveResponse {
  companies: CompanyRun[]
  riders: ActiveRider[]
  people: number
}

/** Active riders: the riders in each company's own most recent payout. */
export function ActiveRidersPage() {
  const { user } = useAuth()
  const showMoney = user?.role !== 'recruiter'
  const [data, setData] = useState<ActiveResponse | null>(null)
  const [filters, setFilters] = useUrlRecord('f')
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setBusy(true); setError(null)
    api.get<ActiveResponse>('/riders/active')
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false))
  }, [])

  const rows = useMemo(() => data?.riders ?? [], [data])
  const searched = useMemo(() => {
    const s = q.trim().toLowerCase()
    if (!s) return rows
    return rows.filter((r) =>
      [r.name, r.rider_id, r.hub, r.mob_no, r.ev_id, String(r.person_id ?? '')]
        .some((v) => (v ?? '').toLowerCase().includes(s)))
  }, [rows, q])
  const filtered = useMemo(() => applyFilters(searched, filters), [searched, filters])
  const { sorted: visible, sortKey, sortDir, toggleSort } = useSort(filtered, { urlKey: 'sort' })
  const people = new Set(visible.map((r) => r.person_id).filter((p) => p != null)).size
  const picked = filters.company ?? ''

  return (
    <div className="max-w-7xl mx-auto">
      <h1 className="text-2xl font-bold mb-1">Active Riders</h1>
      <p className="text-slate-500 text-sm mb-6">
        Only the riders who were in their own company's most recent payout. Each company
        is judged on its last processed run, so the dates differ by company.
      </p>

      {error && <p className="text-red-400 text-sm mb-3">{error}</p>}
      {busy && <Spinner />}

      {data && (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-3 mb-4">
          {data.companies.map((c) => (
            <button key={c.company}
                    onClick={() => setFilters({ ...filters, company: picked === c.company ? '' : c.company })}
                    className={'panel p-3 text-left transition ' +
                      (picked === c.company ? 'ring-2 ring-brand' : 'hover:bg-slate-50')}>
              <p className="text-xs text-slate-500">{c.company}</p>
              <p className="text-lg font-semibold">{c.riders}</p>
              <p className="text-[11px] text-slate-500">{c.cycle_start} → {c.cycle_end}</p>
            </button>
          ))}
          {data.companies.length === 0 && !busy &&
            <p className="text-sm text-slate-500 col-span-full">No payout has been processed yet.</p>}
        </div>
      )}

      <div className="flex flex-wrap gap-3 items-end mb-3">
        <label className="block text-xs">
          <span className="block text-slate-600">Search</span>
          <input value={q} onChange={(e) => setQ(e.target.value)}
                 placeholder="Name, rider id, phone, EV…"
                 className="border rounded px-2 py-1 w-64" />
        </label>
        <ColumnFilters
          rows={rows}
          columns={[
            { key: 'company', label: 'Company' },
            { key: 'hub', label: 'Hub' },
          ]}
          filters={filters}
          onChange={setFilters}
        />
      </div>

      <p className="text-xs text-slate-500 mb-3">
        Showing {visible.length} rider ids ({people} people) of {rows.length}.
      </p>

      <div className="panel overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-100 text-left">
            <tr>
              <SortableTh tag="name" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Name</SortableTh>
              <SortableTh tag="rider_id" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Rider ID</SortableTh>
              <SortableTh tag="company" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Company</SortableTh>
              <SortableTh tag="hub" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Hub</SortableTh>
              <SortableTh tag="mob_no" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Phone</SortableTh>
              <SortableTh tag="ev_id" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>EV</SortableTh>
              <SortableTh tag="cycle_end" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Last payout</SortableTh>
              {showMoney &&
                <SortableTh tag="payout" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Payout</SortableTh>}
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => (
              <tr key={r.company + '|' + r.rider_id} className="border-t hover:bg-slate-50">
                <td className="px-3 py-2">
                  {r.person_id != null
                    ? <Link to={'/persons/' + r.person_id} className="text-brand underline">{r.name || '—'}</Link>
                    : (r.name || '—')}
                  {r.id_active === false &&
                    <span className="ml-2 text-[11px] text-amber-500">id switched off since</span>}
                </td>
                <td className="px-3 py-2 font-mono text-xs">{r.rider_id}</td>
                <td className="px-3 py-2 text-xs">{r.company}</td>
                <td className="px-3 py-2 text-xs">{r.hub || '-'}</td>
                <td className="px-3 py-2 text-xs">{r.mob_no || '-'}</td>
                <td className="px-3 py-2 text-xs">{r.ev_id || '-'}</td>
                <td className="px-3 py-2 text-xs">{r.cycle_end}</td>
                {showMoney && <td className="px-3 py-2 text-right">{fmt(r.payout)}</td>}
              </tr>
            ))}
          </tbody>
        </table>
        {visible.length === 0 && !busy &&
          <p className="p-6 text-center text-slate-500 text-sm">No riders match.</p>}
      </div>
    </div>
  )
}
