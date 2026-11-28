import { DragEvent, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, savePayoutWorkbook } from '../api/client'
import type { RunResponse } from '../api/types'
import { money } from '../lib/format'
import { PayoutDownload } from './PayoutDownload'

/** Process Payout for Zomato: drop the daily FE reports for the cycle.
 *
 *  Both vendor reports go in together — ZFPP (Flat and Salary ids) and
 *  MFFLEET (Commission ids). Each FE ID is paid by the type set on its rider
 *  row: Flat = orders × rate, Salary = salary less days short + incentives,
 *  Commission = Zomato pays the rider itself, so it is listed and not paid.
 *  A day a committed cycle already paid is left out. Nothing is written
 *  until Commit, and Commit is only enabled for the inputs previewed. */

type DayFile = { name: string; vendor: string; day: string; rows: number }
type Rider = {
  rider_id: string; name: string; known: boolean; vendor: string; type: string
  days_present: number; orders: number; rain_orders: number; login_hours: number
  gross: number; working: string; rent: number; released: number; held: boolean
}
type Detail = {
  files: DayFile[]
  riders: Rider[]
  by_type: { type: string; riders: number; orders: number; gross: number }[]
  needs_type: Rider[]
  already_paid: { rider_id: string; day: string; cycle: string; orders: number }[]
}
type RunResp = {
  result: { warnings: string[]; unknown_riders: { rider_id: string; name: string }[] }
  zomato: Detail
  xlsx?: RunResponse['xlsx']
  run?: RunResponse['run']
}

const TYPE_TONE: Record<string, string> = {
  Flat: 'text-sky-300', Salary: 'text-violet-300', Commission: 'text-slate-400', 'Not set': 'text-amber-300',
}

export function ZomatoPanel({ company }: { company: string }) {
  const [files, setFiles] = useState<File[]>([])
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [data, setData] = useState<RunResp | null>(null)
  const [previewKey, setPreviewKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const key = JSON.stringify([files.map((f) => f.name + f.size), start, end])

  useEffect(() => {
    api.get<{ cycle_start: string; cycle_end: string }>('/companies/' + encodeURIComponent(company) + '/next-cycle')
      .then((r) => { setStart(r.cycle_start); setEnd(r.cycle_end) })
      .catch(() => {})
  }, [company])

  function take(list: FileList | null) {
    if (!list || !list.length) return
    const next = Array.from(list).filter((f) => /\.xlsx?$/i.test(f.name))
    setFiles([...files.filter((f) => !next.some((n) => n.name === f.name)), ...next])
    setData(null); setDone(null); setError(null)
  }

  async function run(commit: boolean) {
    if (commit && !window.confirm(`Commit ${company} ${start} → ${end}? This writes the ledger.`)) return
    setBusy(true); setError(null)
    try {
      const fd = new FormData()
      fd.append('company', company); fd.append('cycle_start', start); fd.append('cycle_end', end)
      fd.append('commit', commit ? 'true' : 'false')
      files.forEach((f) => fd.append('files', f))
      const r = await api.postForm<RunResp>('/cycles/run', fd)
      setData(r)
      if (commit) {
        setDone(`Committed ${company} ${start} → ${end}.`); setPreviewKey('')
        if (r.xlsx) {
          try { savePayoutWorkbook(r.xlsx) } catch { setError('The workbook download could not start. Download it from Processed payouts.') }
        }
      } else { setDone(null); setPreviewKey(key) }
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Failed to process'
      if (commit) setPreviewKey('')
      setError(commit ? message + ' Check Processed payouts before trying again.' : message)
    } finally { setBusy(false) }
  }

  const z = data?.zomato
  const blocked = (z?.needs_type.length ?? 0) > 0 || (data?.result.unknown_riders.length ?? 0) > 0

  return (
    <div className="panel p-6 mb-6">
      <h2 className="font-semibold mb-1">{company} — FE reports</h2>
      <p className="text-xs text-slate-500 mb-3">
        Drop every daily report for the cycle, both vendors (ZFPP and MFFLEET). Each FE ID is paid by its type on the
        rider page: <b>Flat</b> = orders × rate, <b>Salary</b> = salary less days short + incentives,
        <b> Commission</b> = Zomato pays the rider; listed, not paid.
      </p>
      <div
        onDragOver={(e: DragEvent) => e.preventDefault()}
        onDrop={(e: DragEvent) => { e.preventDefault(); take(e.dataTransfer.files) }}
        onClick={() => inputRef.current?.click()}
        className="border-2 border-dashed rounded-lg p-6 text-center cursor-pointer text-sm text-slate-400 hover:border-slate-400"
      >
        {files.length
          ? `${files.length} file${files.length === 1 ? '' : 's'} chosen — drop more or click to add`
          : 'Drop the FE report files for this cycle — or click to choose.'}
        <input ref={inputRef} type="file" accept=".xlsx,.xls" multiple className="hidden"
               onChange={(e) => { take(e.target.files); e.target.value = '' }} />
      </div>
      {files.length > 0 && (
        <button type="button" onClick={() => { setFiles([]); setData(null) }} className="text-xs underline text-slate-400 mt-1">
          clear files
        </button>
      )}

      <div className="flex flex-wrap items-end gap-3 mt-4">
        <label className="text-sm">Cycle start
          <input type="date" value={start} onChange={(e) => setStart(e.target.value)} className="block border rounded px-2 py-1" />
        </label>
        <label className="text-sm">Cycle end
          <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} className="block border rounded px-2 py-1" />
        </label>
        <button type="button" disabled={busy || !files.length || !start || !end} onClick={() => void run(false)}
                className="border px-3 py-1.5 rounded disabled:opacity-50">{busy ? 'Working…' : 'Preview'}</button>
        <button type="button" disabled={busy || previewKey !== key || blocked} onClick={() => void run(true)}
                title={blocked ? 'Set every id’s type and onboard unknown ids first' : previewKey !== key ? 'Preview these exact files and dates first' : ''}
                className="bg-emerald-600 hover:bg-emerald-500 text-white px-3 py-1.5 rounded disabled:opacity-50">
          Commit &amp; download
        </button>
      </div>
      {error && <p className="text-red-400 mt-3 text-sm">{error}</p>}
      {done && <div className="flex items-center gap-3 flex-wrap mt-3 text-sm">
        <span className="text-emerald-300">{done}</span>
        {data?.run && <PayoutDownload run={data.run} />}
        <Link to={'/payout-history?company=' + encodeURIComponent(company)} className="text-brand underline">View processed payouts</Link>
      </div>}

      {z && data && (
        <div className="mt-6 space-y-5">
          <div className="flex flex-wrap gap-2 text-xs">
            {z.files.map((f) => (
              <span key={f.name + f.day} className="border rounded px-2 py-0.5" title={f.vendor}>
                {f.day} · {/MFFLEET/i.test(f.vendor) ? 'MFFLEET' : 'ZFPP'} · {f.rows} FE
              </span>
            ))}
          </div>
          <div className="flex flex-wrap gap-3 text-sm">
            {z.by_type.map((t) => (
              <div key={t.type} className="panel px-3 py-2">
                <span className={TYPE_TONE[t.type] ?? ''}>{t.type}</span> · {t.riders} rider{t.riders === 1 ? '' : 's'} · {t.orders} orders
                {t.type !== 'Commission' && t.type !== 'Not set' && <> · <b>₹{money(t.gross)}</b></>}
              </div>
            ))}
          </div>

          {data.result.warnings.length > 0 && (
            <ul className="text-xs text-amber-300 list-disc pl-5">
              {data.result.warnings.map((w, i) => <li key={i}>{w}</li>)}
            </ul>
          )}

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-slate-500 border-b border-edge-soft">
                <tr>
                  <th className="py-1 pr-2">Rider</th><th className="pr-2">Type</th><th className="pr-2">Days</th>
                  <th className="pr-2">Orders</th><th className="pr-2">Login h</th>
                  <th className="pr-2 text-right">Gross</th><th className="pr-2 text-right">Rent</th><th className="pr-2 text-right">Net</th>
                  <th>Working</th>
                </tr>
              </thead>
              <tbody>
                {z.riders.map((r) => (
                  <tr key={r.rider_id} className="border-b border-edge-soft/40">
                    <td className="py-1 pr-2">{r.name}<span className="text-xs text-slate-500"> · {r.rider_id}{r.known ? '' : ' · not on roster'}</span></td>
                    <td className={'pr-2 text-xs ' + (TYPE_TONE[r.type] ?? '')}>{r.type}</td>
                    <td className="pr-2">{r.days_present}</td>
                    <td className="pr-2">{r.orders}</td>
                    <td className="pr-2">{r.login_hours}</td>
                    <td className="pr-2 text-right">{r.type === 'Commission' || r.type === 'Not set' ? '—' : `₹${money(r.gross)}`}</td>
                    <td className="pr-2 text-right">{r.rent ? `₹${money(r.rent)}` : '—'}</td>
                    <td className="pr-2 text-right">
                      {r.type === 'Commission' || r.type === 'Not set' ? '—' : r.held ? <span className="text-amber-300">HOLD</span> : `₹${money(r.released)}`}
                    </td>
                    <td className="text-xs text-slate-400">{r.working}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {z.needs_type.length > 0 && (
            <div className="text-sm">
              <div className="font-semibold mb-1 text-amber-300">Set a type before committing ({z.needs_type.length})</div>
              <p className="text-xs text-slate-500 mb-1">These ids are on the ZFPP report but nobody has said Flat or Salary. Open each rider and pick the type under the company name, then preview again.</p>
              <ul className="text-xs">
                {z.needs_type.map((r) => <li key={r.rider_id}>{r.name} · {r.rider_id} · {r.orders} orders</li>)}
              </ul>
            </div>
          )}
          {data.result.unknown_riders.length > 0 && (
            <div className="text-sm">
              <div className="font-semibold mb-1">Not on the {company} roster ({data.result.unknown_riders.length})</div>
              <p className="text-xs text-slate-500 mb-1">Onboard them (Riders → onboard unknowns, company {company}), set their type, and preview again.</p>
              <ul className="text-xs">
                {data.result.unknown_riders.map((u) => <li key={u.rider_id}>{u.name} · {u.rider_id}</li>)}
              </ul>
            </div>
          )}
          {z.already_paid.length > 0 && (
            <div className="text-xs text-slate-400">
              {z.already_paid.length} rider-day(s) already paid by an earlier cycle — left out.
            </div>
          )}
        </div>
      )}
    </div>
  )
}
