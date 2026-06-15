import { FormEvent, useEffect, useState } from 'react'
import { api } from '../api/client'
import { Spinner } from '../components/Spinner'
import type { Company, CycleResult, InactiveRow, RiderResultRow, RunResponse } from '../api/types'

function isoToday(offset = 0): string {
  const d = new Date()
  d.setDate(d.getDate() + offset)
  return d.toISOString().slice(0, 10)
}

function fmt(n: number): string {
  return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function downloadBase64(b64: string, filename: string, mime: string) {
  const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))
  const blob = new Blob([bytes], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export function ProcessPayoutPage() {
  const [companies, setCompanies] = useState<Company[]>([])
  const [company, setCompany] = useState('')
  const [cycleStart, setCycleStart] = useState(isoToday(-7))
  const [cycleEnd, setCycleEnd] = useState(isoToday(-1))
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<CycleResult | null>(null)
  const [busy, setBusy] = useState<'preview' | 'commit' | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .get<Company[]>('/companies')
      .then((cs) => {
        const active = cs.filter((c) => c.is_active)
        setCompanies(active)
        if (active.length) setCompany((cur) => cur || active[0].company_name)
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  // When the company changes, fetch the next cycle's start/end and auto-fill the date inputs.
  useEffect(() => {
    if (!company) return
    api
      .get<{ cycle_start: string; cycle_end: string; last_cycle_end: string | null }>(
        '/companies/' + encodeURIComponent(company) + '/next-cycle'
      )
      .then((r) => {
        setCycleStart(r.cycle_start)
        setCycleEnd(r.cycle_end)
      })
      .catch(() => {
        // Non-fatal: keep whatever defaults are already in the inputs.
      })
  }, [company])

  async function submit(commit: boolean, e?: FormEvent) {
    e?.preventDefault()
    if (!file || !company) return
    setBusy(commit ? 'commit' : 'preview')
    setError(null)
    try {
      const form = new FormData()
      form.set('company', company)
      form.set('cycle_start', cycleStart)
      form.set('cycle_end', cycleEnd)
      form.set('commit', commit ? 'true' : 'false')
      form.set('file', file)
      const r = await api.postForm<RunResponse>('/cycles/run', form)
      setPreview(r.result)
      if (commit && r.xlsx) {
        downloadBase64(r.xlsx.content_base64, r.xlsx.filename, r.xlsx.mime)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to process')
    } finally {
      setBusy(null)
    }
  }

  const t = preview?.totals ?? {}

  return (
    <div className="max-w-6xl mx-auto">
      <h1 className="text-2xl font-bold mb-1">Process Payout</h1>
      <p className="text-slate-500 text-sm mb-6">
        Upload a company payout file, preview the result, then commit when ready.
        Commit writes everything atomically and returns the styled workbook for download.
      </p>

      <form onSubmit={(e) => submit(false, e)} className="bg-white rounded-lg shadow p-6 mb-6">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div>
            <label className="block text-sm font-medium mb-1">Company</label>
            <select
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              className="w-full border rounded px-3 py-2"
            >
              {companies.map((c) => (
                <option key={c.company_name} value={c.company_name}>{c.company_name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Cycle Start</label>
            <input
              type="date" value={cycleStart}
              onChange={(e) => setCycleStart(e.target.value)}
              className="w-full border rounded px-3 py-2"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Cycle End</label>
            <input
              type="date" value={cycleEnd}
              onChange={(e) => setCycleEnd(e.target.value)}
              className="w-full border rounded px-3 py-2"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Payout File (.xlsx)</label>
            <input
              type="file" accept=".xlsx"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="w-full text-sm"
            />
          </div>
        </div>
        <div className="flex flex-wrap gap-3 mt-4 items-center">
          <button
            type="submit" disabled={!file || !!busy}
            className="bg-slate-200 hover:bg-slate-300 px-4 py-2 rounded font-medium disabled:opacity-50"
          >
            {busy === 'preview' ? 'Previewing...' : 'Preview (dry run)'}
          </button>
          <button
            type="button" onClick={() => void submit(true)} disabled={!file || !!busy}
            className="bg-brand hover:bg-brand-700 text-white px-4 py-2 rounded font-medium disabled:opacity-50"
          >
            {busy === 'commit' ? 'Committing...' : 'Commit & Download'}
          </button>
          {busy && <Spinner />}
        </div>
        {error && <p className="text-red-600 mt-3 text-sm">{error}</p>}
      </form>

      {preview && (
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-baseline gap-3 mb-4 flex-wrap">
            <h2 className="text-xl font-bold">
              {preview.committed ? 'Committed' : 'Preview'} — {preview.company} cycle {preview.cycle_start} → {preview.cycle_end}
            </h2>
            <span className={'text-xs px-2 py-0.5 rounded ' + (preview.committed ? 'bg-green-200' : 'bg-slate-200')}>
              {preview.committed ? 'WRITTEN' : 'DRY RUN'}
            </span>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
            <StatCard label="Riders paid" value={(t.riders_paid ?? 0).toString()} />
            <StatCard label="Total release" value={fmt(t.total_release ?? 0)} />
            <StatCard label="Rent charged" value={fmt(t.total_rent_charged ?? 0)} />
            <StatCard label="Arrears recovered" value={fmt(t.total_arrears_recovered ?? 0)} />
            <StatCard label="Rent missed" value={fmt(t.rent_missed_this_cycle ?? 0)} />
          </div>

          {preview.warnings.length > 0 && (
            <details className="mb-4 bg-amber-50 border border-amber-200 rounded p-3">
              <summary className="font-medium cursor-pointer">
                {preview.warnings.length} warning(s)
              </summary>
              <ul className="mt-2 text-sm list-disc list-inside text-amber-900">
                {preview.warnings.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            </details>
          )}

          <Section title={`PAY (${preview.pay_rows.length})`} color="bg-green-100">
            <PayTable rows={preview.pay_rows} />
          </Section>
          {preview.dues_rows.length > 0 && (
            <Section title={`DUES (${preview.dues_rows.length})`} color="bg-orange-100">
              <PayTable rows={preview.dues_rows} />
            </Section>
          )}
          {preview.inactive_rows.length > 0 && (
            <Section title={`INACTIVE (${preview.inactive_rows.length})`} color="bg-red-100">
              <InactiveTable rows={preview.inactive_rows} />
            </Section>
          )}
        </div>
      )}
    </div>
  )
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-slate-50 rounded p-3">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="text-lg font-semibold">{value}</p>
    </div>
  )
}

function Section({ title, color, children }: { title: string; color: string; children: React.ReactNode }) {
  return (
    <div className="mb-6">
      <h3 className={'font-semibold mb-2 px-3 py-1 rounded inline-block ' + color}>{title}</h3>
      <div className="overflow-x-auto border rounded">{children}</div>
    </div>
  )
}

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return <th className={'px-3 py-2 font-medium ' + (right ? 'text-right' : '')}>{children}</th>
}
function Td({ children, right, className = '' }: { children: React.ReactNode; right?: boolean; className?: string }) {
  return <td className={'px-3 py-2 ' + (right ? 'text-right ' : '') + className}>{children}</td>
}

function PayTable({ rows }: { rows: RiderResultRow[] }) {
  return (
    <table className="w-full text-sm">
      <thead className="bg-slate-100 text-left">
        <tr>
          <Th>Person</Th><Th>Rider</Th><Th>Name</Th><Th>Hub</Th><Th>Vehicle</Th><Th>EV</Th>
          <Th right>Rent</Th><Th right>Gross</Th><Th right>Prev Dues</Th><Th right>Deductions</Th>
          <Th right>Released</Th><Th right>Carry Fwd</Th><Th right>COD Hold</Th><Th>Remarks</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => {
          const prevDues = Math.max(0, -r.prev_balance)
          const carry = Math.max(0, -r.new_balance)
          const deductions = r.payout - r.released
          return (
            <tr key={r.rider_id + ':' + r.company} className={'border-t ' + (r.is_hold ? 'bg-amber-100' : '')}>
              <Td>{r.person_id}</Td><Td>{r.rider_id}</Td><Td>{r.name}</Td>
              <Td>{r.hub ?? '-'}</Td><Td>{r.vehicle ?? '-'}</Td>
              <Td>{r.ev_id ?? '-'}</Td>
              <Td right>{fmt(r.rent)}</Td>
              <Td right>{fmt(r.payout)}</Td>
              <Td right>{fmt(prevDues)}</Td>
              <Td right>{fmt(deductions)}</Td>
              <Td right className="font-semibold">{fmt(r.released)}</Td>
              <Td right>{fmt(carry)}</Td>
              <Td right>{fmt(r.cod_hold)}</Td>
              <Td>{r.remarks}</Td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

function InactiveTable({ rows }: { rows: InactiveRow[] }) {
  return (
    <table className="w-full text-sm">
      <thead className="bg-slate-100 text-left">
        <tr>
          <Th>Person</Th><Th>Name</Th><Th>Vehicle</Th><Th>EV</Th>
          <Th right>Balance</Th><Th right>Arrears</Th><Th>Reason</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.person_id} className="border-t bg-red-50">
            <Td>{r.person_id}</Td>
            <Td>{r.name}</Td>
            <Td>{r.vehicle ?? '-'}</Td>
            <Td>{(r.ev_id ?? '-') + (r.model ? ' (' + r.model + ')' : '')}</Td>
            <Td right>{fmt(r.current_balance)}</Td>
            <Td right>{fmt(r.arrears_outstanding)}</Td>
            <Td className="text-xs">{r.reason}</Td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
