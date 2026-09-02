import { useEffect, useState } from 'react'
import { useUrlString } from '../state/useUrlState'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Spinner } from '../components/Spinner'

const fmt = (n: number) =>
  n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })

interface UploadSummary {
  id: number
  file_name: string
  uploaded_at: string | null
  uploaded_by: string | null
  line_count: number
  success_count: number
  failed_count: number
  unmatched_count: number
  notes: string | null
}

interface AbsentRider {
  person_id: number
  display_name: string
  expected_amount: number
  earliest_cycle: string | null
  latest_cycle: string | null
  companies: string
  accounts: string
}

interface PaymentLine {
  id: number
  line_no: number | null
  pymt_mode: string | null
  bene_name: string | null
  bene_account_no: string | null
  bene_ifsc: string | null
  amount: number
  remark: string | null
  pymt_date: string | null
  bank_status: string | null
  utr: string | null
  customer_ref: string | null
  person_id: number | null
  matched_name: string | null
  match_status: 'matched' | 'name_matched' | 'unmatched'
  resolution_method: 'bank_ok' | 'upi_paid' | 'credit_ledger' | null
  resolved_at: string | null
  resolved_by: string | null
}

export function PaymentsPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin' || user?.role === 'creator'
  const [uploads, setUploads] = useState<UploadSummary[]>([])
  const [picked, setPicked] = useState<number | null>(null)
  const [detail, setDetail] = useState<{
    upload: UploadSummary
    lines: PaymentLine[]
    absent?: AbsentRider[]
    window?: { from: string; to: string }
  } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const reloadList = () => {
    api.get<UploadSummary[]>('/payments/uploads')
      .then(setUploads).catch((e: Error) => setError(e.message))
  }
  useEffect(reloadList, [])

  useEffect(() => {
    if (picked == null) { setDetail(null); return }
    setBusy(true)
    api.get<{ upload: UploadSummary; lines: PaymentLine[] }>('/payments/uploads/' + picked)
      .then(setDetail).catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false))
  }, [picked])

  return (
    <div className="max-w-7xl mx-auto">
      <h1 className="text-2xl font-bold mb-1">Payments</h1>
      <p className="text-slate-500 text-sm mb-6">
        Upload the bank MIS report after every batch. We'll parse each
        beneficiary line, match it to a rider by account + IFSC (with name
        fallback), and surface failed / unmatched transfers so you can mark
        them paid by UPI or credit the rider's ledger.
      </p>

      {isAdmin && <UploadCard onUploaded={(id) => { reloadList(); setPicked(id) }} />}

      <h2 className="font-semibold mt-6 mb-2">Recent uploads</h2>
      <div className="bg-white rounded-xl border border-slate-200/80 shadow-card overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-100 text-left">
            <tr>
              <Th>File</Th><Th>Uploaded</Th><Th>By</Th>
              <Th right>Lines</Th>
              <Th right>Success</Th>
              <Th right>Pending</Th>
              <Th right>Unmatched</Th>
              <Th />
            </tr>
          </thead>
          <tbody>
            {uploads.map((u) => (
              <tr key={u.id} className={'border-t hover:bg-slate-50 ' +
                                       (picked === u.id ? 'bg-amber-50' : '')}>
                <Td>{u.file_name}</Td>
                <Td className="text-xs">{u.uploaded_at ?? ''}</Td>
                <Td className="text-xs">{u.uploaded_by ?? ''}</Td>
                <Td right>{u.line_count}</Td>
                <Td right className="text-emerald-700">{u.success_count}</Td>
                <Td right className={u.failed_count > 0 ? 'text-red-700 font-semibold' : 'text-slate-400'}>
                  {u.failed_count}
                </Td>
                <Td right className={u.unmatched_count > 0 ? 'text-amber-700' : 'text-slate-400'}>
                  {u.unmatched_count}
                </Td>
                <Td>
                  <button onClick={() => setPicked(u.id)}
                          className="text-xs text-brand underline">
                    {picked === u.id ? 'Open' : 'View'}
                  </button>
                </Td>
              </tr>
            ))}
          </tbody>
        </table>
        {uploads.length === 0 && (
          <p className="p-6 text-center text-slate-500 text-sm">
            No uploads yet — drop the bank MIS PDF above.
          </p>
        )}
      </div>

      {error && <p className="text-red-600 text-sm mt-3">{error}</p>}
      {busy && <Spinner />}

      {detail && (
        <UploadDetail detail={detail}
                      isAdmin={isAdmin}
                      onChanged={() => {
                        reloadList()
                        api.get<{ upload: UploadSummary; lines: PaymentLine[] }>(
                          '/payments/uploads/' + detail.upload.id
                        ).then(setDetail).catch(() => {})
                      }} />
      )}
    </div>
  )
}

function UploadCard({ onUploaded }: { onUploaded: (id: number) => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [tone, setTone] = useState<'ok' | 'err'>('ok')

  async function submit() {
    if (!file) return
    setBusy(true); setMsg(null)
    try {
      const form = new FormData()
      form.set('file', file)
      const r = await api.postForm<{ upload_id: number; line_count: number;
                                     success_count: number; failed_count: number;
                                     unmatched_count: number }>(
        '/payments/upload', form,
      )
      setTone('ok'); setMsg(
        `Parsed ${r.line_count} lines — ${r.success_count} success, ${r.failed_count} failed, ${r.unmatched_count} unmatched.`,
      )
      setFile(null)
      onUploaded(r.upload_id)
    } catch (e) {
      setTone('err'); setMsg(e instanceof Error ? e.message : 'Upload failed')
    } finally { setBusy(false) }
  }
  return (
    <div className="bg-white rounded-xl border border-slate-200/80 shadow-card p-4 flex flex-wrap gap-3 items-end">
      <label className="block flex-1 min-w-[260px]">
        <span className="block text-xs text-slate-600">Bank MIS PDF</span>
        <input type="file" accept=".pdf"
               onChange={(e) => setFile(e.target.files?.[0] ?? null)}
               className="w-full text-sm" />
      </label>
      <button onClick={submit} disabled={!file || busy}
              className="bg-brand hover:bg-brand-700 text-white px-3 py-1.5 rounded disabled:opacity-50">
        {busy ? 'Parsing…' : 'Upload & parse'}
      </button>
      {msg && <span className={'text-xs ' + (tone === 'err' ? 'text-red-600' : 'text-green-700')}>{msg}</span>}
    </div>
  )
}

function UploadDetail({ detail, isAdmin, onChanged }:
  { detail: { upload: UploadSummary; lines: PaymentLine[]
              absent?: AbsentRider[]
              window?: { from: string; to: string } }
    isAdmin: boolean
    onChanged: () => void }) {
  const absent = detail.absent ?? []
  const [tab, setTab] = useUrlString('tab', 'pending') as [
    'pending' | 'success' | 'resolved',
    (v: 'pending' | 'success' | 'resolved') => void,
  ]
  const lines = detail.lines
  const pending = lines.filter((l) => !l.resolution_method)
  const success = lines.filter((l) => l.resolution_method === 'bank_ok')
  const resolved = lines.filter(
    (l) => l.resolution_method === 'upi_paid' || l.resolution_method === 'credit_ledger',
  )
  const shown = tab === 'pending' ? pending
              : tab === 'success' ? success
              :                     resolved

  const totalAmount = shown.reduce((a, l) => a + (l.amount || 0), 0)

  return (
    <section className="mt-6">
      <h2 className="font-semibold mb-2">
        {detail.upload.file_name} — {lines.length} lines, ₹{fmt(lines.reduce((a, l) => a + l.amount, 0))} total
      </h2>

      {absent.length > 0 && (
        <details className="mb-3 bg-rose-50 border border-rose-200 rounded p-3" open>
          <summary className="cursor-pointer font-medium text-rose-900">
            {absent.length} rider(s) completely absent from this file
            {detail.window && (
              <span className="ml-2 text-xs text-rose-700 font-normal">
                (window {detail.window.from} → {detail.window.to})
              </span>
            )}
          </summary>
          <p className="text-xs text-rose-800 mt-1 mb-2">
            They had a RELEASE in a cycle that overlaps this bank statement
            but their name and account number don't appear in any line.
            Probably paid by UPI or yet to be paid. Matched by name and
            account, not internal ID.
          </p>
          <div className="overflow-x-auto bg-white rounded border border-rose-100">
            <table className="w-full text-xs">
              <thead className="bg-rose-100 text-left">
                <tr>
                  <Th>Person</Th>
                  <Th>Name</Th>
                  <Th>Companies</Th>
                  <Th>Cycle</Th>
                  <Th>Accounts on file</Th>
                  <Th right>Expected</Th>
                </tr>
              </thead>
              <tbody>
                {absent.map((a) => (
                  <tr key={a.person_id} className="border-t">
                    <Td>
                      <Link to={'/persons/' + a.person_id} className="text-brand underline">
                        #{a.person_id}
                      </Link>
                    </Td>
                    <Td>{a.display_name}</Td>
                    <Td className="text-[11px]">{a.companies}</Td>
                    <Td className="text-[11px]">
                      {a.earliest_cycle} → {a.latest_cycle}
                    </Td>
                    <Td className="text-[11px] font-mono">{a.accounts}</Td>
                    <Td right className="font-semibold text-rose-700">
                      {fmt(a.expected_amount)}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
      <div className="flex gap-2 mb-3">
        {(['pending', 'success', 'resolved'] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
                  className={'text-xs px-3 py-1 rounded ' +
                    (tab === t ? 'bg-brand text-white' : 'bg-slate-200 hover:bg-slate-300')}>
            {t === 'pending' ? `Pending (${pending.length})`
             : t === 'success' ? `Bank success (${success.length})`
             :                   `Resolved by you (${resolved.length})`}
          </button>
        ))}
      </div>
      <div className="bg-white rounded-xl border border-slate-200/80 shadow-card overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-100 text-left">
            <tr>
              <Th>Beneficiary</Th>
              <Th>Person</Th>
              <Th>Match</Th>
              <Th>A/c · IFSC</Th>
              <Th right>Amount</Th>
              <Th>Bank status</Th>
              <Th>UTR / Ref</Th>
              <Th>Remark</Th>
              {tab === 'pending' && isAdmin && <Th>Action</Th>}
              {tab === 'resolved' && <Th>Resolved as</Th>}
            </tr>
          </thead>
          <tbody>
            {shown.map((l) => (
              <LineRow key={l.id} line={l} mode={tab} isAdmin={isAdmin} onChanged={onChanged} />
            ))}
          </tbody>
        </table>
        {shown.length === 0 && (
          <p className="p-6 text-center text-slate-500 text-sm">
            Nothing here.
          </p>
        )}
      </div>
      <p className="text-xs text-slate-500 mt-1">
        Showing {shown.length} lines · total ₹{fmt(totalAmount)}
      </p>
    </section>
  )
}

function LineRow({ line, mode, isAdmin, onChanged }:
  { line: PaymentLine; mode: 'pending' | 'success' | 'resolved'
    isAdmin: boolean; onChanged: () => void }) {
  const [busy, setBusy] = useState<'upi' | 'credit' | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function resolve(method: 'upi_paid' | 'credit_ledger') {
    setBusy(method === 'upi_paid' ? 'upi' : 'credit'); setError(null)
    try {
      await api.post('/payments/lines/' + line.id + '/resolve', { method })
      onChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed')
    } finally { setBusy(null) }
  }

  const matchPill =
    line.match_status === 'matched'
      ? <span className="text-xs px-1.5 py-0.5 rounded bg-emerald-100">acc+ifsc</span>
      : line.match_status === 'name_matched'
      ? <span className="text-xs px-1.5 py-0.5 rounded bg-amber-100">by name</span>
      : <span className="text-xs px-1.5 py-0.5 rounded bg-red-100">none</span>

  return (
    <tr className="border-t hover:bg-slate-50">
      <Td>{line.bene_name ?? '-'}</Td>
      <Td>
        {line.person_id
          ? <Link to={'/persons/' + line.person_id} className="text-brand underline">
              #{line.person_id} {line.matched_name ? '· ' + line.matched_name : ''}
            </Link>
          : <span className="text-slate-400 text-xs">unmatched</span>}
      </Td>
      <Td>{matchPill}</Td>
      <Td className="text-xs">
        <div>{line.bene_account_no || '-'}</div>
        <div className="text-slate-500">{line.bene_ifsc || ''}</div>
      </Td>
      <Td right className="font-medium">{fmt(line.amount)}</Td>
      <Td>
        <span className={'text-xs px-1.5 py-0.5 rounded ' +
          ((line.bank_status || '').toLowerCase().startsWith('success')
            ? 'bg-green-100' : 'bg-red-100')}>
          {line.bank_status || '-'}
        </span>
      </Td>
      <Td className="text-xs">
        <div>{line.utr ?? ''}</div>
        <div className="text-slate-500">{line.customer_ref ?? ''}</div>
      </Td>
      <Td className="text-xs">{line.remark ?? ''}</Td>
      {mode === 'pending' && isAdmin && (
        <Td>
          <div className="flex flex-col gap-1">
            <button onClick={() => resolve('upi_paid')} disabled={!!busy}
                    className="text-xs bg-brand text-white px-2 py-0.5 rounded disabled:opacity-50"
                    title="Operator paid via UPI; no ledger change.">
              {busy === 'upi' ? '…' : 'Paid via UPI'}
            </button>
            <button onClick={() => resolve('credit_ledger')} disabled={!!busy || !line.person_id}
                    className="text-xs bg-amber-600 text-white px-2 py-0.5 rounded disabled:opacity-50"
                    title="Bank failed; credit the rider's ledger so the amount carries.">
              {busy === 'credit' ? '…' : 'Add to ledger'}
            </button>
            {error && <span className="text-xs text-red-600">{error}</span>}
          </div>
        </Td>
      )}
      {mode === 'resolved' && (
        <Td>
          <span className={'text-xs px-1.5 py-0.5 rounded ' +
            (line.resolution_method === 'upi_paid'
              ? 'bg-emerald-100' : 'bg-amber-100')}>
            {line.resolution_method === 'upi_paid' ? 'paid via UPI' : 'credited ledger'}
          </span>
          <div className="text-xs text-slate-500 mt-1">
            {line.resolved_at ?? ''} · {line.resolved_by ?? ''}
          </div>
        </Td>
      )}
    </tr>
  )
}

function Th({ children, right }: { children?: React.ReactNode; right?: boolean }) {
  return <th className={'px-3 py-2 font-medium text-xs ' + (right ? 'text-right' : '')}>{children}</th>
}
function Td({ children, right, className = '' }:
  { children: React.ReactNode; right?: boolean; className?: string }) {
  return <td className={'px-3 py-2 ' + (right ? 'text-right ' : '') + className}>{children}</td>
}
