import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { ExportButton } from '../components/ExportButton'
import { Spinner } from '../components/Spinner'
import type { Company, TransactionOut } from '../api/types'

const fmt = (n: number) =>
  n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })

const EVENT_COLOR: Record<string, string> = {
  PAYOUT: 'bg-green-100', RENT: 'bg-orange-100', RENT_MISSED: 'bg-red-100',
  RENT_RECOVERED: 'bg-blue-100', DUES_CARRY: 'bg-yellow-100', ADJUSTMENT: 'bg-purple-100',
  DEDUCTION_SWITCH: 'bg-emerald-100', EV_SWAP: 'bg-indigo-100', OPENING: 'bg-slate-100',
}
const EVENT_TYPES = Object.keys(EVENT_COLOR)

export function TransactionsPage() {
  const [txns, setTxns] = useState<TransactionOut[]>([])
  const [companies, setCompanies] = useState<Company[]>([])
  const [eventType, setEventType] = useState('')
  const [company, setCompany] = useState('')
  const [limit, setLimit] = useState(200)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.get<Company[]>('/companies').then(setCompanies).catch(() => {})
  }, [])

  useEffect(() => {
    const p = new URLSearchParams()
    if (eventType) p.set('event_type', eventType)
    if (company) p.set('company', company)
    p.set('limit', String(limit))
    setBusy(true); setError(null)
    api.get<TransactionOut[]>('/ledger' + (p.toString() ? '?' + p : ''))
      .then(setTxns)
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false))
  }, [eventType, company, limit])

  return (
    <div className="max-w-7xl mx-auto">
      <div className="flex items-start justify-between gap-3 mb-1">
        <h1 className="text-2xl font-bold">Transactions</h1>
        <ExportButton path="/ledger/export" name="transactions.xlsx" />
      </div>
      <p className="text-slate-500 text-sm mb-6">
        Append-only ledger across all riders. Click a Person ID to open the full per-rider history.
      </p>

      <div className="bg-white rounded-lg shadow p-4 mb-4 flex flex-wrap gap-4 items-end">
        <div className="flex-1 min-w-[140px]">
          <label className="block text-xs font-medium mb-1">Event type</label>
          <select value={eventType} onChange={(e) => setEventType(e.target.value)}
                  className="w-full border rounded px-3 py-2 text-sm">
            <option value="">All</option>
            {EVENT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <div className="flex-1 min-w-[140px]">
          <label className="block text-xs font-medium mb-1">Company</label>
          <select value={company} onChange={(e) => setCompany(e.target.value)}
                  className="w-full border rounded px-3 py-2 text-sm">
            <option value="">All</option>
            {companies.map((c) => <option key={c.company_name}>{c.company_name}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium mb-1">Limit</label>
          <select value={limit} onChange={(e) => setLimit(parseInt(e.target.value))}
                  className="border rounded px-3 py-2 text-sm">
            <option value={50}>50</option>
            <option value={200}>200</option>
            <option value={500}>500</option>
            <option value={1000}>1000</option>
          </select>
        </div>
        {busy && <Spinner />}
      </div>

      {error && <p className="text-red-600 text-sm mb-3">{error}</p>}

      <div className="bg-white rounded-lg shadow overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-100 text-left">
            <tr>
              <Th>ID</Th><Th>Person</Th><Th>Rider / Co</Th><Th>Cycle</Th>
              <Th>Event</Th><Th right>Amount</Th><Th right>Bal After</Th>
              <Th>Days</Th><Th>Remarks</Th><Th>When</Th>
            </tr>
          </thead>
          <tbody>
            {txns.map((t) => (
              <tr key={t.id} className="border-t hover:bg-slate-50">
                <Td>{t.id}</Td>
                <Td><Link to={'/persons/' + t.person_id} className="text-brand underline">
                  #{t.person_id}
                </Link></Td>
                <Td className="text-xs">{(t.rider_id || '-') + ' / ' + (t.company || '-')}</Td>
                <Td className="text-xs">{t.cycle_start} → {t.cycle_end}</Td>
                <Td>
                  <span className={'text-xs px-1.5 py-0.5 rounded ' +
                    (EVENT_COLOR[t.event_type] ?? 'bg-slate-100')}>
                    {t.event_type}
                  </span>
                </Td>
                <Td right>{fmt(t.amount)}</Td>
                <Td right>{fmt(t.balance_after)}</Td>
                <Td>{t.days ?? '-'}</Td>
                <Td className="text-xs">{t.remarks ?? ''}</Td>
                <Td className="text-xs">{t.created_at ?? ''}</Td>
              </tr>
            ))}
          </tbody>
        </table>
        {txns.length === 0 && !busy && (
          <p className="p-6 text-center text-slate-500 text-sm">
            No transactions yet — run a payout cycle to populate the ledger.
          </p>
        )}
      </div>
    </div>
  )
}

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return <th className={'px-3 py-2 font-medium text-xs ' + (right ? 'text-right' : '')}>{children}</th>
}
function Td({ children, right, className = '' }: { children: React.ReactNode; right?: boolean; className?: string }) {
  return <td className={'px-3 py-2 ' + (right ? 'text-right ' : '') + className}>{children}</td>
}
