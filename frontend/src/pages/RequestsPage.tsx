import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { useApi } from '../hooks/useApi'
import { rupees } from '../lib/format'
import { Spinner } from '../components/Spinner'

/** A recruiter's request to add or deduct money on a rider. Recruiters can
 *  only ASK; an admin approves (optionally for a different amount) or
 *  rejects, and the approval posts the ledger adjustment. */
export interface MoneyRequest {
  id: number
  created_at: string
  created_by: string
  person_id: number
  person_name: string
  direction: 'credit' | 'debit'
  amount: number
  reason: string
  status: 'open' | 'approved' | 'rejected'
  resolved_by: string | null
  resolved_at: string | null
  resolution_note: string | null
  applied_amount: number | null
}

const STATUS_CLS: Record<string, string> = {
  open: 'bg-amber-400/15 text-amber-200',
  approved: 'bg-emerald-500/15 text-emerald-300',
  rejected: 'bg-rose-500/15 text-rose-300',
}

export function RequestsPage() {
  const { user } = useAuth()
  const isRecruiter = user?.role === 'recruiter'
  const [tab, setTab] = useState<'open' | 'all'>('open')
  const list = useApi<MoneyRequest[]>(`/requests${tab === 'open' ? '?status=open' : ''}`, [tab])

  return (
    <div className="max-w-6xl mx-auto">
      <h1 className="page-title mb-1">{isRecruiter ? 'My Requests' : 'Money Requests'}</h1>
      <p className="text-slate-500 text-sm mb-6">
        {isRecruiter
          ? 'Credits and deductions you have asked for. An admin approves or rejects each one; nothing changes on the ledger until then.'
          : 'Recruiters cannot touch money themselves — they ask. Approving posts the adjustment to the rider\'s ledger; you can approve for a different amount.'}
      </p>

      <div className="flex items-center gap-2 mb-3">
        {(['open', 'all'] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
                  className={'px-3 py-1 rounded-lg text-sm ' + (tab === t ? 'bg-brand-500/20 text-white' : 'text-slate-500 hover:text-slate-800')}>
            {t === 'open' ? 'Open' : 'All'}
          </button>
        ))}
      </div>

      <section className="panel overflow-hidden">
        {list.loading ? (
          <div className="p-6"><Spinner /></div>
        ) : list.error ? (
          <div className="p-4 text-sm text-critical">{list.error}</div>
        ) : !list.data?.length ? (
          <div className="p-4 text-sm text-slate-500">
            {tab === 'open' ? 'No open requests.' : 'No requests yet.'}
          </div>
        ) : (
          list.data.map((r) => <RequestRow key={r.id} r={r} canResolve={!isRecruiter} onDone={list.reload} />)
        )}
      </section>
    </div>
  )
}

function RequestRow({ r, canResolve, onDone }: { r: MoneyRequest; canResolve: boolean; onDone: () => void }) {
  const [mode, setMode] = useState<'idle' | 'approve' | 'reject'>('idle')
  const [amount, setAmount] = useState(String(r.amount))
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const act = async () => {
    setBusy(true); setError(null)
    try {
      const body: Record<string, unknown> = {}
      if (note.trim()) body.note = note.trim()
      if (mode === 'approve' && Number(amount) !== r.amount) body.amount = Number(amount)
      await api.post(`/requests/${r.id}/${mode}`, body)
      setMode('idle'); onDone()
    } catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }

  return (
    <div className="px-4 py-3 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-slate-100 first:border-t-0">
      <div className="min-w-[200px]">
        <Link to={`/persons/${r.person_id}`} className="font-medium text-slate-900 hover:text-brand-600">
          {r.person_name}
        </Link>
        <div className="text-xs text-slate-500">#{r.id} · by {r.created_by} · {r.created_at}</div>
      </div>
      <div className="text-sm flex-1 min-w-[240px]">
        <span className={'font-semibold ' + (r.direction === 'credit' ? 'text-emerald-300' : 'text-rose-300')}>
          {r.direction === 'credit' ? 'Add' : 'Deduct'} {rupees(r.amount)}
        </span>
        <span className="text-slate-500"> — {r.reason}</span>
        {r.status !== 'open' && (
          <div className="text-xs text-slate-500 mt-0.5">
            {r.status} by {r.resolved_by} on {r.resolved_at}
            {r.status === 'approved' && r.applied_amount != null && r.applied_amount !== r.amount
              ? ` for ${rupees(r.applied_amount)}` : ''}
            {r.resolution_note ? ` — ${r.resolution_note}` : ''}
          </div>
        )}
      </div>
      <span className={'pill ' + (STATUS_CLS[r.status] ?? '')}>{r.status}</span>
      {canResolve && r.status === 'open' && (
        mode === 'idle' ? (
          <div className="flex items-center gap-2">
            <button onClick={() => setMode('approve')} className="btn-primary">Approve</button>
            <button onClick={() => setMode('reject')} className="btn-ghost">Reject</button>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            {mode === 'approve' && (
              <label className="text-xs text-slate-500 flex items-center gap-1">
                Amount ₹
                <input type="number" min="0.01" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)}
                       className="border border-slate-300 rounded-lg px-2 py-1 text-sm w-28" />
              </label>
            )}
            <input value={note} onChange={(e) => setNote(e.target.value)}
                   placeholder={mode === 'approve' ? 'note (optional)' : 'reason for rejecting (optional)'}
                   className="border border-slate-300 rounded-lg px-2 py-1 text-sm w-56" />
            <button onClick={act} disabled={busy || (mode === 'approve' && !(Number(amount) > 0))} className="btn-primary">
              {busy ? '…' : mode === 'approve' ? 'Confirm approve' : 'Confirm reject'}
            </button>
            <button onClick={() => setMode('idle')} disabled={busy} className="btn-ghost">Cancel</button>
          </div>
        )
      )}
      {error && <div className="w-full text-sm text-critical">{error}</div>}
    </div>
  )
}
