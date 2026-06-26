import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Spinner } from '../components/Spinner'
import { ColumnFilters, applyFilters } from '../components/TableFilters'
import { useUrlRecord } from '../state/useUrlState'
import { ExportButton } from '../components/ExportButton'
import { SortableTh, useSort } from '../components/Sortable'

const fmt = (n: number | null | undefined) =>
  (n ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })

interface CodRow {
  person_id: number
  display_name: string
  total_pending: number
  entry_count: number
  earliest_cycle_start: string | null
  latest_cycle_end: string | null
  companies: string | null
  hubs: string | null
  recent_payout: number | null
  recent_payout_cycle: string | null
}

interface CodEntry {
  id: number
  cycle_start: string
  cycle_end: string
  company: string
  rider_id: string | null
  order_number: string | null
  amount: number
  payment_mode: string | null
  txn_status: string | null
  source: string
  cleared_at: string | null
  cleared_by: string | null
}

export function CodPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin' || user?.role === 'creator'
  const [rows, setRows] = useState<CodRow[]>([])
  const [filters, setFilters] = useUrlRecord('f')
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [openClearFor, setOpenClearFor] = useState<CodRow | null>(null)

  const reload = () => {
    setBusy(true); setError(null)
    api.get<CodRow[]>('/cod')
      .then(setRows)
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false))
  }
  useEffect(reload, [])

  const filtered = useMemo(() => applyFilters(rows, filters), [rows, filters])
  const { sorted: visible, sortKey, sortDir, toggleSort } = useSort(filtered, { urlKey: 'sort' })

  const totals = visible.reduce(
    (a, r) => ({
      pending: a.pending + r.total_pending,
      entries: a.entries + r.entry_count,
    }),
    { pending: 0, entries: 0 },
  )

  return (
    <div className="max-w-7xl mx-auto">
      <div className="flex items-start justify-between gap-3 mb-1">
        <h1 className="text-2xl font-bold">COD Pending</h1>
        <ExportButton path="/cod/export" name="cod_pending.xlsx" ids={visible.map((r) => r.person_id)} />
      </div>
      <p className="text-slate-500 text-sm mb-6">
        COD amounts that companies couldn't clear from a payout. These do not
        deduct from the rider's balance; mark each as cleared once you've
        collected the cash. You can optionally credit the rider's ledger by
        the payout amount when marking clear.
      </p>

      <ColumnFilters
        rows={rows}
        columns={[
          { key: 'companies', label: 'Company' },
          { key: 'hubs',      label: 'Hub' },
        ]}
        filters={filters}
        onChange={setFilters}
      />

      <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-4">
        <Stat label="Riders with pending COD" value={visible.length.toString()} />
        <Stat label="Total pending COD" value={fmt(totals.pending)} bold />
        <Stat label="Open entries" value={totals.entries.toString()} />
      </div>

      {busy && <Spinner />}
      {error && <p className="text-red-600 text-sm mb-3">{error}</p>}
      <p className="text-xs text-slate-500 mb-3">Showing {visible.length} of {rows.length} riders.</p>

      <div className="bg-white/80 backdrop-blur-xl rounded-xl shadow-card transition-shadow duration-200 hover:shadow-glass overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-100 text-left">
            <tr>
              <SortableTh tag="person_id" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Person</SortableTh>
              <SortableTh tag="display_name" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Name</SortableTh>
              <SortableTh tag="companies" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Companies</SortableTh>
              <SortableTh tag="hubs" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Hub</SortableTh>
              <SortableTh tag="total_pending" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Total COD</SortableTh>
              <SortableTh tag="entry_count" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Entries</SortableTh>
              <SortableTh tag="recent_payout" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Recent payout</SortableTh>
              <SortableTh tag="recent_payout_cycle" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Last cycle</SortableTh>
              {isAdmin && <Th>{''}</Th>}
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => (
              <tr key={r.person_id} className="border-t hover:bg-slate-50">
                <Td><Link to={'/persons/' + r.person_id} className="text-brand underline">#{r.person_id}</Link></Td>
                <Td>{r.display_name}</Td>
                <Td className="text-xs">{r.companies || '-'}</Td>
                <Td className="text-xs">{r.hubs || '-'}</Td>
                <Td right className="font-semibold text-red-700">{fmt(r.total_pending)}</Td>
                <Td right>{r.entry_count}</Td>
                <Td right>{r.recent_payout != null ? fmt(r.recent_payout) : '-'}</Td>
                <Td className="text-xs">{r.recent_payout_cycle ?? '-'}</Td>
                {isAdmin && (
                  <Td>
                    <button onClick={() => setOpenClearFor(r)}
                            className="text-xs bg-brand text-white px-2 py-1 rounded">
                      Mark cleared
                    </button>
                  </Td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        {visible.length === 0 && !busy &&
          <p className="p-6 text-center text-slate-500 text-sm">No pending COD. Tidy.</p>}
      </div>

      {openClearFor && (
        <ClearModal row={openClearFor}
                    onClose={() => setOpenClearFor(null)}
                    onCleared={() => { setOpenClearFor(null); reload() }} />
      )}
    </div>
  )
}

function ClearModal({ row, onClose, onCleared }:
  { row: CodRow; onClose: () => void; onCleared: () => void }) {
  const [entries, setEntries] = useState<CodEntry[]>([])
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [creditPayout, setCreditPayout] = useState(false)
  const [ledgerAmount, setLedgerAmount] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.get<CodEntry[]>(`/cod/${row.person_id}/entries`)
      .then((es) => {
        setEntries(es)
        setSelectedIds(new Set(es.filter((e) => e.cleared_at === null).map((e) => e.id)))
      })
      .catch((e: Error) => setError(e.message))
  }, [row.person_id])

  const totalSelected = entries
    .filter((e) => selectedIds.has(e.id))
    .reduce((a, e) => a + e.amount, 0)

  useEffect(() => {
    if (creditPayout) setLedgerAmount(String(row.recent_payout ?? 0))
  }, [creditPayout, row.recent_payout])

  async function submit() {
    setBusy(true); setError(null)
    try {
      const body: Record<string, unknown> = { person_id: row.person_id }
      body.entry_ids = Array.from(selectedIds)
      const amt = parseFloat(ledgerAmount)
      if (Number.isFinite(amt) && amt !== 0) {
        body.ledger_amount = amt
        body.reason = reason || `COD clearance for ${row.display_name}`
      }
      await api.post('/cod/clear', body)
      onCleared()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center p-4 z-50">
      <div className="bg-white/90 backdrop-blur-xl rounded-2xl shadow-xl w-full max-w-2xl max-h-[90vh] flex flex-col">
        <div className="px-5 py-3 border-b flex items-center justify-between">
          <div>
            <h3 className="font-semibold">Mark COD cleared — {row.display_name}</h3>
            <p className="text-xs text-slate-500">Pending: {fmt(row.total_pending)} across {row.entry_count} entries</p>
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-700">✕</button>
        </div>
        <div className="px-5 py-3 overflow-y-auto">
          <p className="text-xs text-slate-500 mb-2">Select which entries you've collected:</p>
          <table className="w-full text-xs">
            <thead className="bg-slate-50 text-left">
              <tr>
                <th className="px-2 py-1">
                  <input type="checkbox"
                         checked={entries.filter((e) => e.cleared_at === null).every((e) => selectedIds.has(e.id))}
                         onChange={(e) => setSelectedIds(
                           e.target.checked
                             ? new Set(entries.filter((x) => x.cleared_at === null).map((x) => x.id))
                             : new Set(),
                         )} />
                </th>
                <th className="px-2 py-1">Cycle</th>
                <th className="px-2 py-1">Company</th>
                <th className="px-2 py-1">Order #</th>
                <th className="px-2 py-1 text-right">Amount</th>
                <th className="px-2 py-1">Status</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.id} className={'border-t ' + (e.cleared_at !== null ? 'opacity-50' : '')}>
                  <td className="px-2 py-1">
                    <input type="checkbox" disabled={e.cleared_at !== null}
                           checked={selectedIds.has(e.id)}
                           onChange={(ev) => {
                             const s = new Set(selectedIds)
                             if (ev.target.checked) s.add(e.id); else s.delete(e.id)
                             setSelectedIds(s)
                           }} />
                  </td>
                  <td className="px-2 py-1">{e.cycle_end}</td>
                  <td className="px-2 py-1">{e.company}</td>
                  <td className="px-2 py-1">{e.order_number ?? '-'}</td>
                  <td className="px-2 py-1 text-right">{fmt(e.amount)}</td>
                  <td className="px-2 py-1">{e.cleared_at ? `cleared ${e.cleared_at}` : 'pending'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-xs text-slate-500 mt-2">
            Selected total: <span className="font-semibold">{fmt(totalSelected)}</span>
          </p>

          <div className="mt-4 border-t pt-3 space-y-2">
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={creditPayout}
                     onChange={(e) => setCreditPayout(e.target.checked)} />
              Add the recent payout ({fmt(row.recent_payout ?? 0)}) to their ledger
            </label>
            <div className="flex gap-2 items-end">
              <label className="block text-xs flex-1">
                <span className="block text-slate-600">Ledger amount (positive = credit, negative = debit)</span>
                <input type="number" step="0.01" value={ledgerAmount}
                       onChange={(e) => setLedgerAmount(e.target.value)}
                       className="w-full border rounded px-2 py-1" />
              </label>
              <label className="block text-xs flex-1">
                <span className="block text-slate-600">Reason</span>
                <input value={reason} onChange={(e) => setReason(e.target.value)}
                       placeholder="e.g. cash collected on 2026-06-15"
                       className="w-full border rounded px-2 py-1" />
              </label>
            </div>
            <p className="text-xs text-slate-500">
              Leave the amount blank to just close the COD without touching the ledger.
            </p>
          </div>

          {error && <p className="text-red-600 text-xs mt-3">{error}</p>}
        </div>
        <div className="px-5 py-3 border-t flex justify-end gap-2">
          <button onClick={onClose} disabled={busy}
                  className="text-sm px-3 py-1.5 rounded bg-slate-200 hover:bg-slate-300">Cancel</button>
          <button onClick={submit} disabled={busy || selectedIds.size === 0}
                  className="text-sm px-3 py-1.5 rounded bg-brand text-white hover:bg-brand-700 disabled:opacity-50">
            {busy ? 'Saving…' : `Mark ${selectedIds.size} cleared`}
          </button>
        </div>
      </div>
    </div>
  )
}

function Stat({ label, value, bold }: { label: string; value: string; bold?: boolean }) {
  return <div className="bg-white/80 backdrop-blur-xl rounded-xl shadow-card transition-shadow duration-200 hover:shadow-glass p-3">
    <p className="text-xs text-slate-500">{label}</p>
    <p className={'text-lg ' + (bold ? 'font-bold' : 'font-semibold')}>{value}</p>
  </div>
}
function Th({ children }: { children: React.ReactNode }) {
  return <th className="px-3 py-2 font-medium text-xs">{children}</th>
}
function Td({ children, right, className = '' }:
  { children: React.ReactNode; right?: boolean; className?: string }) {
  return <td className={'px-3 py-2 ' + (right ? 'text-right ' : '') + className}>{children}</td>
}
