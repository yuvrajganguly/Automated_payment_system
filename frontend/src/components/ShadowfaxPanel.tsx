import { DragEvent, useRef, useState } from 'react'
import { api } from '../api/client'
import { money } from '../lib/format'

/** Process Payout for a per-order company on the pincode ratecard (Shadowfax).
 *
 *  Drop every daily Vendor_data download for the cycle at once. The server
 *  reads them all, keeps the newest file's row for each rider × day × pincode
 *  (the files are cumulative and revised), prices each row off the ratecard,
 *  leaves out days a committed cycle already paid, and runs the ordinary
 *  cycle on the result: rent, arrears, dues, holds, the workbook. Nothing is
 *  written until Commit, and Commit is only enabled for the inputs previewed. */

type SourceFile = { name: string; file_date: string; rows: number; order_dates: string[]; dated_by: string }
type Rider = {
  rider_id: string; name: string; hub: string; file_hub: string; days: number; orders: number
  ppd_orders: number; cod_orders: number; rvp_orders: number; sdd_orders: number; club_orders: number
  gross: number; sfx_payout: number; margin: number; rent: number; released: number
  bank: string; flags: string[]; known: boolean; ztp_penalty: number
}
type Detail = {
  files: SourceFile[]
  order_dates: { order_date: string; found: boolean; source_file: string | null }[]
  riders: Rider[]
  already_paid: { rider_id: string; name: string; order_date: string; cycle: string; orders: number; gross: number }[]
  revised_after_payment: { rider_id: string; name: string; order_date: string; cycle: string; orders_delta: number; revised_pay: number }[]
  ztp: { rider_id: string; name: string; awb_number: string; fraud_type: string; penalty: number; created_date: string }[]
  totals: { orders: number; gross: number; sfx_payout: number; margin: number }
}
type RunResp = {
  result: { warnings: string[]; unknown_riders: { rider_id: string; name: string; hub: string; gross?: number; orders?: number }[]
            pay_rows: { rider_id: string; is_hold: boolean; released: number }[]; dues_rows: { rider_id: string; is_hold: boolean; released: number }[] }
  shadowfax: Detail
  xlsx?: { filename: string; content_base64: string; mime: string }
}
type Scan = { files: SourceFile[]; suggested_cycle_start: string | null; suggested_cycle_end: string | null; last_cycle_end: string | null }

function downloadBase64(b64: string, filename: string, mime: string) {
  const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))
  const url = URL.createObjectURL(new Blob([bytes], { type: mime }))
  const a = document.createElement('a'); a.href = url; a.download = filename; a.click()
  URL.revokeObjectURL(url)
}

export function ShadowfaxPanel({ company, onTypeCounts }: { company: string; onTypeCounts: () => void }) {
  const [files, setFiles] = useState<File[]>([])
  const [scan, setScan] = useState<Scan | null>(null)
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [ztp, setZtp] = useState<Record<string, boolean>>({})
  const [data, setData] = useState<RunResp | null>(null)
  const [previewKey, setPreviewKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const key = JSON.stringify([files.map((f) => f.name + f.size), start, end, ztp])

  async function take(list: FileList | null) {
    if (!list || !list.length) return
    const next = Array.from(list).filter((f) => f.name.toLowerCase().endsWith('.xlsx'))
    const merged = [...files.filter((f) => !next.some((n) => n.name === f.name)), ...next]
    setFiles(merged); setData(null); setDone(null); setError(null)
    setBusy(true)
    try {
      const fd = new FormData(); fd.append('company', company)
      merged.forEach((f) => fd.append('files', f))
      const s = await api.postForm<Scan>('/cycles/parse-sheet', fd)
      setScan(s)
      if (s.suggested_cycle_start) setStart(s.suggested_cycle_start)
      if (s.suggested_cycle_end) setEnd(s.suggested_cycle_end)
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not read the files') }
    finally { setBusy(false) }
  }

  async function run(commit: boolean) {
    if (commit && !window.confirm(`Commit ${company} ${start} → ${end}? This writes the ledger.`)) return
    setBusy(true); setError(null)
    try {
      const fd = new FormData()
      fd.append('company', company); fd.append('cycle_start', start); fd.append('cycle_end', end)
      fd.append('commit', commit ? 'true' : 'false')
      files.forEach((f) => fd.append('files', f))
      const chosen = Object.entries(ztp).filter(([, v]) => v).map(([k]) => k)
      if (chosen.length) fd.append('ztp_apply', JSON.stringify(chosen))
      const r = await api.postForm<RunResp>('/cycles/run', fd)
      setData(r)
      if (commit) {
        if (r.xlsx) downloadBase64(r.xlsx.content_base64, r.xlsx.filename, r.xlsx.mime)
        setDone(`Committed ${company} ${start} → ${end}.`); setPreviewKey('')
      } else setPreviewKey(key)
    } catch (e) { setError(e instanceof Error ? e.message : 'Failed') }
    finally { setBusy(false) }
  }

  const s = data?.shadowfax
  const held = new Set([...(data?.result.pay_rows ?? []), ...(data?.result.dues_rows ?? [])].filter((r) => r.is_hold).map((r) => r.rider_id))

  return (
    <div className="panel p-6 mb-6">
      <div className="flex items-center gap-3 mb-3">
        <h2 className="font-semibold">{company} — Vendor_data files</h2>
        <button type="button" onClick={onTypeCounts} className="ml-auto text-xs underline text-slate-400">
          type counts instead
        </button>
      </div>

      <div
        onDragOver={(e: DragEvent) => e.preventDefault()}
        onDrop={(e: DragEvent) => { e.preventDefault(); void take(e.dataTransfer.files) }}
        onClick={() => inputRef.current?.click()}
        className="border-2 border-dashed rounded-lg p-6 text-center cursor-pointer text-sm text-slate-400 hover:border-slate-400"
      >
        Drop all Vendor_data files for this cycle — or click to choose. Daily files repeat and revise
        earlier days; the newest file wins, nothing is added twice.
        <input ref={inputRef} type="file" accept=".xlsx" multiple className="hidden"
               onChange={(e) => { void take(e.target.files); e.target.value = '' }} />
      </div>

      {scan && (
        <div className="mt-4 text-xs">
          <div className="font-semibold mb-1">{scan.files.length} file{scan.files.length === 1 ? '' : 's'} read</div>
          <div className="flex flex-wrap gap-2">
            {scan.files.map((f) => (
              <span key={f.name} className="border rounded px-2 py-0.5" title={f.order_dates.join(', ')}>
                {f.file_date}{f.dated_by === 'content' ? '*' : ''} · {f.rows} rows
              </span>
            ))}
          </div>
          {scan.last_cycle_end && <div className="text-slate-500 mt-1">Last committed cycle ended {scan.last_cycle_end}.</div>}
        </div>
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
        <button type="button" disabled={busy || previewKey !== key} onClick={() => void run(true)}
                title={previewKey !== key ? 'Preview these exact files and dates first' : ''}
                className="bg-emerald-600 hover:bg-emerald-500 text-white px-3 py-1.5 rounded disabled:opacity-50">
          Commit &amp; download
        </button>
      </div>
      {error && <p className="text-red-400 mt-3 text-sm">{error}</p>}
      {done && <p className="text-emerald-300 mt-3 text-sm">{done}</p>}

      {s && data && (
        <div className="mt-6 space-y-5">
          <div className="flex flex-wrap gap-3 text-sm">
            <div className="panel px-3 py-2">Rider pay <b>₹{money(s.totals.gross)}</b></div>
            <div className="panel px-3 py-2">Shadowfax pays us <b>₹{money(s.totals.sfx_payout)}</b></div>
            <div className="panel px-3 py-2">Margin <b>₹{money(s.totals.margin)}</b></div>
            <div className="panel px-3 py-2">{s.totals.orders} orders</div>
          </div>

          <div>
            <div className="text-xs font-semibold mb-1">Order dates in the cycle</div>
            <div className="flex flex-wrap gap-1 text-xs">
              {s.order_dates.map((d) => (
                <span key={d.order_date} title={d.source_file ?? 'not in any file'}
                      className={'rounded px-2 py-0.5 border ' + (d.found ? '' : 'border-amber-500 text-amber-300')}>
                  {d.order_date.slice(5)}{d.found ? ` ← ${d.source_file?.replace('Vendor_data_', '').replace('.xlsx', '')}` : ' missing'}
                </span>
              ))}
            </div>
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
                  <th className="py-1 pr-2">Rider</th><th className="pr-2">Hub</th><th className="pr-2">Days</th>
                  <th className="pr-2">PPD</th><th className="pr-2">COD</th><th className="pr-2">RVP</th><th className="pr-2">SDD</th><th className="pr-2">Club</th>
                  <th className="pr-2 text-right">Gross</th><th className="pr-2 text-right">Rent</th><th className="pr-2 text-right">Net</th>
                  <th className="pr-2">Bank</th><th>Flags</th>
                </tr>
              </thead>
              <tbody>
                {s.riders.filter((r) => r.orders > 0).map((r) => (
                  <tr key={r.rider_id} className="border-b border-edge-soft/40">
                    <td className="py-1 pr-2">{r.name}<span className="text-xs text-slate-500"> · {r.rider_id}{r.known ? '' : ' · not on roster'}</span></td>
                    <td className="pr-2 text-xs">{r.hub || <span className="text-slate-500">{r.file_hub || '—'}</span>}</td>
                    <td className="pr-2">{r.days}</td>
                    <td className="pr-2">{r.ppd_orders}</td><td className="pr-2">{r.cod_orders}</td><td className="pr-2">{r.rvp_orders}</td>
                    <td className="pr-2">{r.sdd_orders}</td><td className="pr-2">{r.club_orders}</td>
                    <td className="pr-2 text-right">₹{money(r.gross)}</td>
                    <td className="pr-2 text-right">₹{money(r.rent)}</td>
                    <td className="pr-2 text-right">{held.has(r.rider_id) ? <span className="text-amber-300">HOLD</span> : `₹${money(r.released)}`}</td>
                    <td className="pr-2 text-xs">{r.bank}</td>
                    <td className="text-xs text-amber-300">{r.flags.join('; ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {data.result.unknown_riders.length > 0 && (
            <div className="text-sm">
              <div className="font-semibold mb-1">Not on the {company} roster ({data.result.unknown_riders.length})</div>
              <p className="text-xs text-slate-500 mb-1">Onboard them (Riders → onboard unknowns, company {company}) and preview again; until then they are not paid.</p>
              <ul className="text-xs">
                {data.result.unknown_riders.map((u) => (
                  <li key={u.rider_id}>{u.name} · {u.rider_id} · {u.hub || 'hub unknown'} · {u.orders ?? 0} orders · ₹{money(u.gross ?? 0)}</li>
                ))}
              </ul>
            </div>
          )}

          {s.ztp.length > 0 && (
            <div className="text-sm">
              <div className="font-semibold mb-1">ZTP penalties Shadowfax took from us — pass on to the rider?</div>
              {Array.from(new Set(s.ztp.map((z) => z.rider_id))).map((rid) => {
                const rows = s.ztp.filter((z) => z.rider_id === rid)
                return (
                  <label key={rid} className="block text-xs">
                    <input type="checkbox" checked={!!ztp[rid]} onChange={(e) => setZtp({ ...ztp, [rid]: e.target.checked })} />{' '}
                    {rows[0].name || rid}: ₹{money(rows.reduce((a, z) => a + z.penalty, 0))} ({rows.map((z) => `${z.awb_number} ${z.fraud_type}`).join(', ')})
                  </label>
                )
              })}
              <p className="text-xs text-slate-500">Ticked penalties are booked as an adjustment against the rider; preview again after changing them.</p>
            </div>
          )}

          {s.already_paid.length > 0 && (
            <div className="text-xs">
              <div className="font-semibold mb-1">Already paid — left out</div>
              {s.already_paid.map((a) => <div key={a.rider_id + a.order_date}>{a.name} · {a.order_date} · in cycle {a.cycle}</div>)}
            </div>
          )}
          {s.revised_after_payment.length > 0 && (
            <div className="text-xs text-amber-300">
              <div className="font-semibold mb-1">Revised after payment — not re-paid</div>
              {s.revised_after_payment.map((a) => (
                <div key={a.rider_id + a.order_date}>
                  {a.name} · {a.order_date}: {a.orders_delta > 0 ? '+' : ''}{a.orders_delta} orders, ₹{money(a.revised_pay)} (paid in {a.cycle})
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
