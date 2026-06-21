/**
 * Shared page for Raft and Blive tabs.
 *
 * Each provider gets its own page (RaftPage / BlivePage) that wraps this with
 * a different `provider` and a different default cadence (weekly vs monthly).
 *
 * Three sections:
 *   1) Date-range picker with provider-appropriate quick chips (last 7d / 4
 *      weeks for Raft; last month / last 3 months for Blive).
 *   2) Period summary — totals + per-EV breakdown for the picked range,
 *      pulled from /api/providers/{provider}/period (which aggregates
 *      ev_daily_ledger filtered to that provider's EVs).
 *   3) Bills history — every uploaded bill for this provider, with an upload
 *      button (Excel/CSV). Clicking a bill opens a tally drawer that compares
 *      each line in the bill against our computed amount and surfaces the
 *      discrepancy.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import { Spinner } from '../components/Spinner'
import { useAuth } from '../auth/AuthContext'

type Cadence = 'weekly' | 'monthly'

interface PerEv {
  ev_id: string
  provider: string
  model: string
  status: string
  holders: string
  days: number
  provider_owed: number
  rider_expected: number
  rider_collected: number
  rider_missed: number
  rider_recovered: number
  rider_pending: number
  shortfall: number
}
interface PeriodResp {
  provider: string
  from: string
  to: string
  totals: {
    provider_owed?: number
    rider_expected?: number
    rider_collected?: number
    rider_missed?: number
    rider_recovered?: number
    rider_pending?: number
    shortfall?: number
    ev_count?: number
    active_evs?: number
    idle_evs?: number
    no_models_registered?: boolean
  }
  per_ev: PerEv[]
}

interface BillRow {
  id: number
  provider: string
  period_start: string
  period_end: string
  bill_total: number
  line_count: number
  file_name: string | null
  uploaded_at: string
  uploaded_by: string | null
  notes: string | null
}

interface BillLine {
  id: number
  bill_id: number
  line_no: number | null
  ev_id_raw: string | null
  ev_id: string | null
  their_amount: number
  status_note: string | null
  our_amount: number | null
  discrepancy: number | null
  notes: string | null
}

interface MasterSyncResp {
  provider: string
  rows_seen: number
  units_added: number
  units_updated: number
  units_unchanged: number
  skipped: { row: { ev_id: string; model_name: string | null }; reason: string }[]
  models_created: { provider: string; model_name: string; weekly_rate: number; needs_rate_review: boolean }[]
  rate_review_needed: string[]
}

const fmt = (n: number | null | undefined) =>
  (n ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })

function todayISO(): string {
  return new Date().toISOString().slice(0, 10)
}

function addDaysISO(iso: string, n: number): string {
  const d = new Date(iso + 'T00:00:00')
  d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}

function startOfMonthISO(iso: string): string {
  return iso.slice(0, 7) + '-01'
}

function endOfMonthISO(iso: string): string {
  const d = new Date(iso + 'T00:00:00')
  const eom = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0))
  return eom.toISOString().slice(0, 10)
}

interface Props {
  provider: 'Raft' | 'Blive'
  cadence: Cadence
}

interface ReconRow {
  person_id: number
  name: string
  ev_ids: string
  expected: number
  collected: number
  missed: number
  recovered: number
  pending: number
  collection_pct: number
  settled_via: string
}
interface ReconResp {
  provider: string
  from: string
  to: string
  rows: ReconRow[]
  totals: { expected: number; collected: number; missed: number; recovered: number;
            pending: number; collection_pct: number; rider_count: number }
}

export function ProviderPage({ provider, cadence }: Props) {
  const { user } = useAuth()
  const canUpload = user?.role === 'admin' || user?.role === 'creator'

  // Default range:
  //   weekly  → most recent Monday..Sunday block
  //   monthly → previous calendar month
  const initialRange = useMemo(() => {
    const t = todayISO()
    if (cadence === 'weekly') {
      const d = new Date(t + 'T00:00:00')
      const wd = (d.getUTCDay() + 6) % 7   // 0 = Monday
      const monday = addDaysISO(t, -wd - 7) // last Monday of the prior week
      return { from: monday, to: addDaysISO(monday, 6) }
    } else {
      // previous full month
      const d = new Date(t + 'T00:00:00')
      const firstOfThisMonth = `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-01`
      const lastOfLastMonth = addDaysISO(firstOfThisMonth, -1)
      return { from: startOfMonthISO(lastOfLastMonth), to: endOfMonthISO(lastOfLastMonth) }
    }
  }, [cadence])

  const [from, setFrom] = useState(initialRange.from)
  const [to,   setTo]   = useState(initialRange.to)
  const [period, setPeriod] = useState<PeriodResp | null>(null)
  const [recon, setRecon] = useState<ReconResp | null>(null)
  const [loadingRecon, setLoadingRecon] = useState(true)
  const [bills,  setBills]  = useState<BillRow[]>([])
  const [loadingPeriod, setLoadingPeriod] = useState(true)
  const [loadingBills,  setLoadingBills]  = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [openBill, setOpenBill] = useState<number | null>(null)
  const [billDetail, setBillDetail] = useState<{ bill: BillRow; lines: BillLine[] } | null>(null)
  const [uploading, setUploading] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const masterInput = useRef<HTMLInputElement>(null)
  const [syncingMaster, setSyncingMaster] = useState(false)
  const [masterReport, setMasterReport] = useState<MasterSyncResp | null>(null)

  // Quick chips depend on cadence
  const chips = cadence === 'weekly'
    ? [
        { label: 'This week', fn: () => {
          const t = todayISO()
          const d = new Date(t + 'T00:00:00')
          const wd = (d.getUTCDay() + 6) % 7
          const monday = addDaysISO(t, -wd)
          return { from: monday, to: addDaysISO(monday, 6) }
        }},
        { label: 'Last week', fn: () => initialRange },
        { label: 'Last 4 weeks', fn: () => ({ from: addDaysISO(todayISO(), -27), to: todayISO() }) },
      ]
    : [
        { label: 'This month',      fn: () => ({ from: startOfMonthISO(todayISO()), to: todayISO() }) },
        { label: 'Last month',      fn: () => initialRange },
        { label: 'Last 3 months',   fn: () => {
          const t = todayISO()
          const d = new Date(t + 'T00:00:00')
          d.setUTCMonth(d.getUTCMonth() - 3)
          return { from: d.toISOString().slice(0, 10), to: t }
        }},
      ]

  async function loadPeriod() {
    setLoadingPeriod(true)
    setErr(null)
    try {
      const data = await api.get<PeriodResp>(
        `/providers/${provider}/period?date_from=${from}&date_to=${to}`,
      )
      setPeriod(data)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to load period')
    } finally {
      setLoadingPeriod(false)
    }
  }

  async function loadBills() {
    setLoadingBills(true)
    try {
      const data = await api.get<BillRow[]>(`/providers/${provider}/bills`)
      setBills(data)
    } finally {
      setLoadingBills(false)
    }
  }

  async function loadRecon() {
    setLoadingRecon(true)
    try {
      const data = await api.get<ReconResp>(
        `/providers/${provider}/reconciliation?date_from=${from}&date_to=${to}`,
      )
      setRecon(data)
    } catch {
      setRecon(null)
    } finally {
      setLoadingRecon(false)
    }
  }

  async function downloadRecon() {
    const url = `/api/providers/${provider}/reconciliation/export?date_from=${from}&date_to=${to}`
    const r = await fetch(url, { credentials: 'include' })
    if (!r.ok) { setErr('Export failed'); return }
    const blob = await r.blob()
    const cd = r.headers.get('content-disposition') ?? ''
    const m = cd.match(/filename="?([^"]+)"?/i)
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = m ? m[1] : `${provider}_reconciliation.xlsx`
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(a.href)
  }

  useEffect(() => { loadPeriod() }, [from, to, provider])  // eslint-disable-line
  useEffect(() => { loadRecon() }, [from, to, provider])   // eslint-disable-line
  useEffect(() => { loadBills() }, [provider])              // eslint-disable-line

  async function openBillDetail(id: number) {
    setOpenBill(id)
    setBillDetail(null)
    try {
      const data = await api.get<{ bill: BillRow; lines: BillLine[] }>(
        `/providers/${provider}/bills/${id}`,
      )
      setBillDetail(data)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to load bill')
    }
  }

  async function deleteBill(id: number) {
    if (!confirm('Delete this bill and its tally? This cannot be undone.')) return
    try {
      await api.delete(`/providers/${provider}/bills/${id}`)
      setOpenBill(null)
      setBillDetail(null)
      loadBills()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Delete failed')
    }
  }

  async function onUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('period_start', from)
      fd.append('period_end',   to)
      await api.postForm(`/providers/${provider}/bills`, fd)
      await loadBills()
    } catch (er) {
      setErr(er instanceof Error ? er.message : 'Upload failed')
    } finally {
      setUploading(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  async function onMasterUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setSyncingMaster(true)
    setMasterReport(null)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const r = await api.postForm<MasterSyncResp>(`/providers/${provider}/master`, fd)
      setMasterReport(r)
      await loadPeriod()  // refresh counts so the user sees the new fleet
    } catch (er) {
      setErr(er instanceof Error ? er.message : 'Master sync failed')
    } finally {
      setSyncingMaster(false)
      if (masterInput.current) masterInput.current.value = ''
    }
  }

  const t = period?.totals || {}

  return (
    <div className="p-6 space-y-6">
      <header className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold">{provider}</h1>
          <p className="text-sm text-slate-500">
            {cadence === 'weekly'
              ? 'Weekly billing — what we owe Raft vs what we collected from riders.'
              : 'Monthly billing — what we owe Blive vs what we collected from riders.'}
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {chips.map(c => (
            <button
              key={c.label}
              onClick={() => { const r = c.fn(); setFrom(r.from); setTo(r.to) }}
              className="px-2 py-1 text-xs rounded border bg-white hover:bg-slate-50"
            >{c.label}</button>
          ))}
          <input type="date" value={from} onChange={e => setFrom(e.target.value)}
                 className="text-sm border rounded px-2 py-1" />
          <span className="text-slate-400 text-xs">to</span>
          <input type="date" value={to} onChange={e => setTo(e.target.value)}
                 className="text-sm border rounded px-2 py-1" />
        </div>
      </header>

      {err && (
        <div className="bg-rose-50 border border-rose-200 text-rose-700 px-3 py-2 rounded text-sm">
          {err}
        </div>
      )}

      {/* Empty-state — no rate card for this provider */}
      {t.no_models_registered && (
        <div className="bg-amber-50 border border-amber-200 text-amber-800 px-4 py-3 rounded text-sm">
          No EV models registered under <b>{provider}</b> yet. Add at least
          one model on the rate card (Settings → EV models) before any EVs
          can be tagged as {provider}.
        </div>
      )}

      {/* Totals */}
      <section className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
        <Card label="EVs in fleet"
              value={`${t.ev_count ?? 0}`}
              tone="slate"
              sub={(t.active_evs != null || t.idle_evs != null)
                ? `${t.active_evs ?? 0} active · ${t.idle_evs ?? 0} idle`
                : undefined} />
        <Card label="Provider Owed"   value={`₹${fmt(t.provider_owed)}`}   tone="indigo" />
        <Card label="Rider Expected"  value={`₹${fmt(t.rider_expected)}`}  tone="slate" />
        <Card label="Rider Collected" value={`₹${fmt(t.rider_collected)}`} tone="emerald" />
        <Card label="Missed"          value={`₹${fmt(t.rider_missed)}`}    tone="amber" />
        <Card label="Recovered"       value={`₹${fmt(t.rider_recovered)}`} tone="sky" />
        <Card label="Shortfall"       value={`₹${fmt(t.shortfall)}`}       tone="rose" />
      </section>

      {/* Master sync result banner */}
      {masterReport && (
        <div className="bg-emerald-50 border border-emerald-200 rounded p-3 text-sm">
          <div className="flex items-center justify-between mb-1">
            <b className="text-emerald-800">Synced from {provider} master</b>
            <button onClick={() => setMasterReport(null)}
                    className="text-slate-400 hover:text-slate-700 text-xs">dismiss</button>
          </div>
          <div className="text-slate-700">
            Read {masterReport.rows_seen} rows ·
            added {masterReport.units_added} EV{masterReport.units_added === 1 ? '' : 's'} ·
            updated {masterReport.units_updated} ·
            unchanged {masterReport.units_unchanged}
            {masterReport.models_created.length > 0 && (
              <> · created models: <i>{masterReport.models_created.map(m => m.model_name).join(', ')}</i></>
            )}
            {masterReport.skipped.length > 0 && (
              <> · skipped {masterReport.skipped.length}</>
            )}
          </div>
          {masterReport.rate_review_needed.length > 0 && (
            <div className="mt-2 text-amber-800 bg-amber-100 px-2 py-1 rounded text-xs">
              ⚠ Set a real weekly rate for these new models (defaulted to ₹1,250):
              <b className="ml-1">{masterReport.rate_review_needed.join(', ')}</b>
            </div>
          )}
        </div>
      )}

      {/* Per-EV table */}
      <section className="bg-white border rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b flex items-center justify-between">
          <h2 className="font-semibold text-slate-700">Per-EV breakdown</h2>
          <div className="flex items-center gap-3">
            {loadingPeriod && <Spinner />}
            {canUpload && (
              <label className="text-xs text-indigo-700 hover:text-indigo-900 cursor-pointer flex items-center gap-1"
                     title="Upload the master Excel the provider sent (EV ID + model columns). New EVs get registered as spare; new model variants are auto-added with the provider's existing rate.">
                <input ref={masterInput} type="file" accept=".xlsx,.xls,.csv,.tsv"
                       onChange={onMasterUpload} className="hidden" />
                {syncingMaster
                  ? <><Spinner /> syncing…</>
                  : <>⇪ Sync fleet from {provider} master</>}
              </label>
            )}
          </div>
        </div>
        <div className="max-h-[460px] overflow-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 sticky top-0">
              <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-3 py-2">EV</th>
                <th className="px-3 py-2">Model</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Holders</th>
                <th className="px-3 py-2 text-right">Days</th>
                <th className="px-3 py-2 text-right">Provider Owed</th>
                <th className="px-3 py-2 text-right">Expected</th>
                <th className="px-3 py-2 text-right">Collected</th>
                <th className="px-3 py-2 text-right">Shortfall</th>
              </tr>
            </thead>
            <tbody>
              {(period?.per_ev || []).map(e => (
                <tr key={e.ev_id}
                    className={'border-t hover:bg-slate-50 ' + (e.days === 0 ? 'text-slate-400' : '')}>
                  <td className="px-3 py-2 font-mono text-xs">{e.ev_id}</td>
                  <td className="px-3 py-2">{e.model}</td>
                  <td className="px-3 py-2">
                    <span className={'text-[10px] px-1.5 py-0.5 rounded ' +
                      (e.status === 'in_use'     ? 'bg-emerald-100 text-emerald-700'
                       : e.status === 'maintenance' ? 'bg-amber-100 text-amber-700'
                       :                              'bg-slate-200 text-slate-600')}>
                      {e.status}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-slate-600 text-xs">{e.holders || '—'}</td>
                  <td className="px-3 py-2 text-right">{e.days}</td>
                  <td className="px-3 py-2 text-right">₹{fmt(e.provider_owed)}</td>
                  <td className="px-3 py-2 text-right">₹{fmt(e.rider_expected)}</td>
                  <td className="px-3 py-2 text-right">₹{fmt(e.rider_collected)}</td>
                  <td className={'px-3 py-2 text-right ' + (e.shortfall > 0 ? 'text-rose-600 font-semibold' : 'text-slate-400')}>
                    ₹{fmt(e.shortfall)}
                  </td>
                </tr>
              ))}
              {!loadingPeriod && (!period || period.per_ev.length === 0) && (
                <tr><td colSpan={9} className="px-3 py-8 text-center text-slate-400">
                  No {provider} EVs registered.
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Per-rider reconciliation (boss report) */}
      <section className="bg-white border rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b flex items-center justify-between">
          <div>
            <h2 className="font-semibold text-slate-700">Rider reconciliation — expected vs collected</h2>
            <p className="text-xs text-slate-500">
              For the range above. &quot;Settled via&quot; is the company payout that actually collected the rent.
            </p>
          </div>
          <button onClick={downloadRecon}
                  className="text-xs font-semibold bg-emerald-600 hover:bg-emerald-700 text-white px-3 py-1.5 rounded">
            Export for boss (.xlsx)
          </button>
        </div>
        <div className="overflow-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50">
              <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-3 py-2">Rider</th>
                <th className="px-3 py-2">EV(s)</th>
                <th className="px-3 py-2 text-right">Expected</th>
                <th className="px-3 py-2 text-right">Collected</th>
                <th className="px-3 py-2 text-right">Missed</th>
                <th className="px-3 py-2 text-right">Pending</th>
                <th className="px-3 py-2 text-right">Collected %</th>
                <th className="px-3 py-2">Settled via</th>
              </tr>
            </thead>
            <tbody>
              {(recon?.rows || []).map(r => (
                <tr key={r.person_id} className="border-t hover:bg-slate-50">
                  <td className="px-3 py-2">{r.name}</td>
                  <td className="px-3 py-2 text-xs text-slate-600">{r.ev_ids}</td>
                  <td className="px-3 py-2 text-right">₹{fmt(r.expected)}</td>
                  <td className="px-3 py-2 text-right text-emerald-700">₹{fmt(r.collected)}</td>
                  <td className="px-3 py-2 text-right text-red-600">₹{fmt(r.missed)}</td>
                  <td className="px-3 py-2 text-right text-amber-600">₹{fmt(r.pending)}</td>
                  <td className="px-3 py-2 text-right">{r.collection_pct}%</td>
                  <td className="px-3 py-2 text-xs text-slate-600">{r.settled_via || '—'}</td>
                </tr>
              ))}
              {recon && recon.rows.length > 0 && (
                <tr className="border-t bg-slate-50 font-semibold">
                  <td className="px-3 py-2" colSpan={2}>TOTAL ({recon.totals.rider_count})</td>
                  <td className="px-3 py-2 text-right">₹{fmt(recon.totals.expected)}</td>
                  <td className="px-3 py-2 text-right text-emerald-700">₹{fmt(recon.totals.collected)}</td>
                  <td className="px-3 py-2 text-right text-red-600">₹{fmt(recon.totals.missed)}</td>
                  <td className="px-3 py-2 text-right text-amber-600">₹{fmt(recon.totals.pending)}</td>
                  <td className="px-3 py-2 text-right">{recon.totals.collection_pct}%</td>
                  <td className="px-3 py-2"></td>
                </tr>
              )}
              {!loadingRecon && (!recon || recon.rows.length === 0) && (
                <tr><td colSpan={8} className="px-3 py-8 text-center text-slate-400">
                  No rider rent activity in this range.
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Bills history */}
      <section className="bg-white border rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b flex items-center justify-between">
          <h2 className="font-semibold text-slate-700">Bills uploaded by {provider}</h2>
          {canUpload && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-500">
                Bill will be tallied against the range shown above.
              </span>
              <input ref={fileInput} type="file" accept=".xlsx,.xls,.csv,.tsv"
                     onChange={onUpload}
                     className="text-xs file:mr-2 file:py-1 file:px-2 file:rounded file:border-0 file:bg-indigo-600 file:text-white" />
              {uploading && <Spinner />}
            </div>
          )}
        </div>
        <div className="overflow-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50">
              <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-3 py-2">Uploaded</th>
                <th className="px-3 py-2">Period</th>
                <th className="px-3 py-2">File</th>
                <th className="px-3 py-2 text-right">Lines</th>
                <th className="px-3 py-2 text-right">Bill Total</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {bills.map(b => (
                <tr key={b.id} className="border-t hover:bg-slate-50 cursor-pointer"
                    onClick={() => openBillDetail(b.id)}>
                  <td className="px-3 py-2 text-xs text-slate-600">{b.uploaded_at?.slice(0, 16).replace('T', ' ')}</td>
                  <td className="px-3 py-2 text-xs">{b.period_start} → {b.period_end}</td>
                  <td className="px-3 py-2 text-xs text-slate-600">{b.file_name || '—'}</td>
                  <td className="px-3 py-2 text-right">{b.line_count}</td>
                  <td className="px-3 py-2 text-right">₹{fmt(b.bill_total)}</td>
                  <td className="px-3 py-2 text-right">
                    <button className="text-indigo-600 text-xs underline">Tally</button>
                  </td>
                </tr>
              ))}
              {!loadingBills && bills.length === 0 && (
                <tr><td colSpan={6} className="px-3 py-8 text-center text-slate-400">
                  No bills uploaded yet.
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Tally drawer */}
      {openBill !== null && (
        <div className="fixed inset-0 bg-black/40 z-40 flex justify-end"
             onClick={() => { setOpenBill(null); setBillDetail(null) }}>
          <div className="bg-white w-full max-w-3xl h-full overflow-auto shadow-xl"
               onClick={e => e.stopPropagation()}>
            <div className="p-4 border-b sticky top-0 bg-white flex items-center justify-between">
              <div>
                <h3 className="font-semibold">Bill #{openBill}</h3>
                {billDetail && (
                  <p className="text-xs text-slate-500">
                    {billDetail.bill.period_start} → {billDetail.bill.period_end}
                    {billDetail.bill.file_name ? ` · ${billDetail.bill.file_name}` : ''}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-2">
                {canUpload && (
                  <button onClick={() => deleteBill(openBill)}
                          className="text-xs text-rose-600 underline">Delete</button>
                )}
                <button onClick={() => { setOpenBill(null); setBillDetail(null) }}
                        className="text-slate-400 hover:text-slate-600">✕</button>
              </div>
            </div>
            {!billDetail
              ? <div className="p-8 flex justify-center"><Spinner /></div>
              : <BillTally lines={billDetail.lines} billTotal={billDetail.bill.bill_total} />}
          </div>
        </div>
      )}
    </div>
  )
}

function Card({ label, value, tone, sub }:
              { label: string; value: string; tone: string; sub?: string }) {
  const map: Record<string, string> = {
    slate:   'bg-slate-50 text-slate-700',
    indigo:  'bg-indigo-50 text-indigo-700',
    emerald: 'bg-emerald-50 text-emerald-700',
    amber:   'bg-amber-50 text-amber-700',
    sky:     'bg-sky-50 text-sky-700',
    rose:    'bg-rose-50 text-rose-700',
  }
  return (
    <div className={'rounded-lg p-3 border ' + (map[tone] || 'bg-white')}>
      <div className="text-xs uppercase tracking-wide opacity-70">{label}</div>
      <div className="text-lg font-semibold mt-1">{value}</div>
      {sub && <div className="text-[10px] opacity-60 mt-0.5">{sub}</div>}
    </div>
  )
}

function BillTally({ lines, billTotal }: { lines: BillLine[]; billTotal: number }) {
  const ours = lines.reduce((s, l) => s + (l.our_amount || 0), 0)
  const diff = billTotal - ours
  const matched      = lines.filter(l => l.our_amount !== null && Math.abs((l.discrepancy || 0)) < 0.5)
  const discrepancy  = lines.filter(l => l.our_amount !== null && Math.abs((l.discrepancy || 0)) >= 0.5)
  const notInLedger  = lines.filter(l => l.our_amount === null)

  return (
    <div className="p-4 space-y-4">
      <div className="grid grid-cols-3 gap-2">
        <Card label="Their Total"  value={`₹${fmt(billTotal)}`} tone="indigo" />
        <Card label="Our Total"    value={`₹${fmt(ours)}`}      tone="slate" />
        <Card label="Difference"
              value={`${diff >= 0 ? '+' : ''}₹${fmt(diff)}`}
              tone={Math.abs(diff) < 1 ? 'emerald' : 'rose'} />
      </div>

      <div className="grid grid-cols-3 gap-2 text-xs text-slate-600">
        <div>✅ Matched: <b>{matched.length}</b></div>
        <div>⚠️ Discrepancy: <b className="text-amber-700">{discrepancy.length}</b></div>
        <div>🚫 Not in our ledger: <b className="text-rose-700">{notInLedger.length}</b></div>
      </div>

      <div className="border rounded overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
              <th className="px-3 py-2">#</th>
              <th className="px-3 py-2">EV</th>
              <th className="px-3 py-2 text-right">Their</th>
              <th className="px-3 py-2 text-right">Ours</th>
              <th className="px-3 py-2 text-right">Δ</th>
              <th className="px-3 py-2">Their Note</th>
              <th className="px-3 py-2">Tally</th>
            </tr>
          </thead>
          <tbody>
            {lines.map(l => {
              const d = l.discrepancy
              const matched = l.our_amount !== null && Math.abs(d || 0) < 0.5
              const tone = l.our_amount === null
                ? 'bg-rose-50'
                : matched ? '' : 'bg-amber-50'
              return (
                <tr key={l.id} className={'border-t ' + tone}>
                  <td className="px-3 py-2 text-slate-500 text-xs">{l.line_no}</td>
                  <td className="px-3 py-2 font-mono text-xs">{l.ev_id_raw || '—'}</td>
                  <td className="px-3 py-2 text-right">₹{fmt(l.their_amount)}</td>
                  <td className="px-3 py-2 text-right">
                    {l.our_amount === null ? <span className="text-rose-600">—</span> : `₹${fmt(l.our_amount)}`}
                  </td>
                  <td className={'px-3 py-2 text-right ' +
                                  (d === null ? 'text-slate-400'
                                  : Math.abs(d) < 0.5 ? 'text-emerald-700'
                                  : 'text-amber-700 font-semibold')}>
                    {d === null ? '—' : `${d >= 0 ? '+' : ''}₹${fmt(d)}`}
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-600">{l.status_note || '—'}</td>
                  <td className="px-3 py-2 text-xs">
                    {l.our_amount === null
                      ? <span className="text-rose-700">Not in ledger</span>
                      : matched
                        ? <span className="text-emerald-700">Matched</span>
                        : <span className="text-amber-700">Discrepancy</span>}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
