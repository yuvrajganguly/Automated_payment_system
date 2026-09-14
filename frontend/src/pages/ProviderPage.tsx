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
import { useUrlString } from '../state/useUrlState'
import { api, saveBlob } from '../api/client'
import { addDaysISO, addMonthsISO, endOfMonthISO, startOfMonthISO, startOfWeekISO, todayISO } from '../lib/dates'
import { Spinner } from '../components/Spinner'
import { useAuth } from '../auth/AuthContext'

type Cadence = 'weekly' | 'monthly'

/**
 * One reconciled line of a provider bill.
 *
 * The tally asks "does their arithmetic match ours". This asks the question
 * the office actually asks on a Monday — did we charge a rider for this, and
 * did that rider pay — so the shape is per-rider rather than per-amount.
 * Money arrives in rupees; the API rupeeizes on the way out.
 */
interface ReconLine {
  ev_id: string
  tag: string
  rider: string | null
  person_id: number | null
  provider_name: string | null
  days: number
  billed: number
  expected: number | null
  charged: number | null
  collected: number | null
  missed: number | null
  hand_booked: number | null
  damage: number | null
  unit_status: string
  note: string
  remark: string | null
  deploy_date: string | null
  overridden?: string[]
}
interface BillReconResp {
  bill_id: number
  period_start: string
  period_end: string
  tags: string[]
  rows: ReconLine[]
  totals: Record<string, number>
  tag_counts: Record<string, number>
}

/** The muted palette the hand-built workbook settled on. Orange first: a
 *  vehicle that came back is not a collection problem. */
const TAG_TONE: Record<string, string> = {
  'Collected':     'bg-emerald-500/10 text-emerald-300 border-emerald-500/20',
  'Partial':       'bg-amber-500/10 text-amber-300 border-amber-500/20',
  'Not collected': 'bg-rose-500/10 text-rose-300 border-rose-500/20',
  'Returned':      'bg-orange-500/10 text-orange-300 border-orange-500/20',
  'Swap':          'bg-sky-500/10 text-sky-300 border-sky-500/20',
  'Charged':       'bg-indigo-500/10 text-indigo-300 border-indigo-500/20',
  'Paid Manually': 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20',
  'Reversed':      'bg-slate-500/10 text-slate-400 border-slate-500/20',
  'Damage':        'bg-slate-500/10 text-slate-400 border-slate-500/20',
}

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

interface Props {
  provider: 'Raft' | 'Blive'
  cadence: Cadence
}

interface ReconRow {
  person_id: number
  name: string
  ev_ids: string
  /** What those vehicles cost us over the range, whatever we billed. */
  provider_owed: number
  expected: number
  collected: number
  missed: number
  recovered: number
  pending: number
  collection_pct: number
  /** Collected against what the vehicle cost us — the one that says whether
   *  the unit paid for itself. collection_pct's denominator is already net of
   *  non-billable days, so a week in the workshop reads 100%. */
  recovery_pct: number
  settled_via: string
}
/** Days in the range nobody was on the hook for. We owed the provider and
 *  could bill no rider; the old query filtered these out entirely. */
interface UnheldRow {
  ev_id: string
  status: string
  days: number
  provider_owed: number
}
interface ReconResp {
  provider: string
  from: string
  to: string
  rows: ReconRow[]
  unheld: UnheldRow[]
  totals: { provider_owed: number; unheld_owed: number; unheld_evs: number;
            expected: number; collected: number; missed: number; recovered: number;
            pending: number; collection_pct: number; recovery_pct: number;
            rider_count: number }
}

export function ProviderPage({ provider, cadence }: Props) {
  const { user } = useAuth()
  const canUpload = user?.role === 'admin' || user?.role === 'creator'

  // Default range:
  //   weekly  → most recent Monday..Sunday block
  //   monthly → previous calendar month
  const initialRange = useMemo(() => {
    // All local-time (lib/dates). The previous helpers mixed a local parse
    // with UTC getters and put every IST user a day (and a week) behind.
    const t = todayISO()
    if (cadence === 'weekly') {
      const monday = addDaysISO(startOfWeekISO(t), -7)   // Monday of the prior week
      return { from: monday, to: addDaysISO(monday, 6) }
    } else {
      // previous full month
      const lastOfLastMonth = addDaysISO(startOfMonthISO(t), -1)
      return { from: startOfMonthISO(lastOfLastMonth), to: endOfMonthISO(lastOfLastMonth) }
    }
  }, [cadence])

  const [from, setFrom] = useUrlString('from', initialRange.from)
  const [to,   setTo]   = useUrlString('to', initialRange.to)
  const [period, setPeriod] = useState<PeriodResp | null>(null)
  const [recon, setRecon] = useState<ReconResp | null>(null)
  const [loadingRecon, setLoadingRecon] = useState(true)
  const [bills,  setBills]  = useState<BillRow[]>([])
  const [loadingPeriod, setLoadingPeriod] = useState(true)
  const [loadingBills,  setLoadingBills]  = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [openBill, setOpenBill] = useState<number | null>(null)
  const [billDetail, setBillDetail] = useState<{ bill: BillRow; lines: BillLine[] } | null>(null)
  // The drawer answers two different questions and they do not belong in one
  // table: "tally" is their arithmetic against ours, "recon" is per rider.
  const [billView, setBillView] = useState<'tally' | 'recon'>('recon')
  const [billRecon, setBillRecon] = useState<BillReconResp | null>(null)
  const [reconBusy, setReconBusy] = useState(false)
  const [uploading, setUploading] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const masterInput = useRef<HTMLInputElement>(null)
  const [syncingMaster, setSyncingMaster] = useState(false)
  const [masterReport, setMasterReport] = useState<MasterSyncResp | null>(null)

  // Quick chips depend on cadence
  const chips = cadence === 'weekly'
    ? [
        { label: 'This week', fn: () => {
          const monday = startOfWeekISO(todayISO())
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
          return { from: addMonthsISO(t, -3), to: t }
        }},
      ]

  async function loadPeriod() {
    setLoadingPeriod(true)
    setErr(null)
    try {
      const data = await api.get<PeriodResp>(`/providers/${provider}/period`,
                                             { query: { date_from: from, date_to: to } })
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
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to load bills')
    } finally {
      setLoadingBills(false)
    }
  }

  async function loadRecon() {
    setLoadingRecon(true)
    try {
      const data = await api.get<ReconResp>(`/providers/${provider}/reconciliation`,
                                            { query: { date_from: from, date_to: to } })
      setRecon(data)
    } catch {
      setRecon(null)
    } finally {
      setLoadingRecon(false)
    }
  }

  async function downloadRecon() {
    try {
      saveBlob(await api.download(`/providers/${provider}/reconciliation/export`, {
        query: { date_from: from, date_to: to },
        fallbackName: `${provider}_reconciliation.xlsx`,
      }))
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Export failed')
    }
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps -- loaders read from/to/provider from closure
  useEffect(() => { loadPeriod() }, [from, to, provider])
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { loadRecon() }, [from, to, provider])
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { loadBills() }, [provider])

  async function openBillDetail(id: number) {
    setOpenBill(id)
    setBillDetail(null)
    try {
      void loadBillRecon(id)
      const data = await api.get<{ bill: BillRow; lines: BillLine[] }>(
        `/providers/${provider}/bills/${id}`,
      )
      setBillDetail(data)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to load bill')
    }
  }

  async function loadBillRecon(id: number) {
    setReconBusy(true)
    try {
      setBillRecon(await api.get<BillReconResp>(`/providers/${provider}/bills/${id}/reconciliation`))
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Could not reconcile that bill')
    } finally {
      setReconBusy(false)
    }
  }

  /** Correct one field on one line. Keyed to the vehicle on the server, so it
   *  carries into next week's bill rather than dying with this one. */
  async function setOverride(id: number, evId: string, field: string, value: string | null) {
    try {
      await api.patch(`/providers/${provider}/bills/${id}/lines/${encodeURIComponent(evId)}`,
                      { field, value })
      await loadBillRecon(id)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Could not save that correction')
    }
  }

  async function downloadBillRecon(id: number) {
    try {
      saveBlob(await api.download(`/providers/${provider}/bills/${id}/reconciliation/export`, {
        json: {},   // an empty body is what makes api.download POST
        fallbackName: `${provider}_bill_${id}.xlsx`,
      }))
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Export failed')
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
              className="px-2 py-1 text-xs rounded border bg-panel hover:bg-slate-50"
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
        <div className="bg-rose-500/10 border border-rose-400/30 text-rose-300 px-3 py-2 rounded text-sm">
          {err}
        </div>
      )}

      {/* Empty-state — no rate card for this provider */}
      {t.no_models_registered && (
        <div className="bg-amber-500/10 border border-amber-400/30 text-amber-200 px-4 py-3 rounded text-sm">
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
        <div className="bg-emerald-500/10 border border-emerald-400/30 rounded p-3 text-sm">
          <div className="flex items-center justify-between mb-1">
            <b className="text-emerald-200">Synced from {provider} master</b>
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
            <div className="mt-2 text-amber-200 bg-amber-500/15 px-2 py-1 rounded text-xs">
              ⚠ Set a real weekly rate for these new models (defaulted to ₹1,250):
              <b className="ml-1">{masterReport.rate_review_needed.join(', ')}</b>
            </div>
          )}
        </div>
      )}

      {/* Per-EV table */}
      <section className="panel overflow-hidden">
        <div className="px-4 py-3 border-b flex items-center justify-between">
          <h2 className="font-semibold text-slate-700">Per-EV breakdown</h2>
          <div className="flex items-center gap-3">
            {loadingPeriod && <Spinner />}
            {canUpload && (
              <label className="text-xs text-indigo-300 hover:text-indigo-200 cursor-pointer flex items-center gap-1"
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
                      (e.status === 'in_use'     ? 'bg-emerald-500/15 text-emerald-300'
                       : e.status === 'maintenance' ? 'bg-amber-500/15 text-amber-300'
                       :                              'bg-slate-200 text-slate-600')}>
                      {e.status}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-slate-600 text-xs">{e.holders || '—'}</td>
                  <td className="px-3 py-2 text-right">{e.days}</td>
                  <td className="px-3 py-2 text-right">₹{fmt(e.provider_owed)}</td>
                  <td className="px-3 py-2 text-right">₹{fmt(e.rider_expected)}</td>
                  <td className="px-3 py-2 text-right">₹{fmt(e.rider_collected)}</td>
                  <td className={'px-3 py-2 text-right ' + (e.shortfall > 0 ? 'text-rose-400 font-semibold' : 'text-slate-400')}>
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
      <section className="panel overflow-hidden">
        <div className="px-4 py-3 border-b flex items-center justify-between">
          <div>
            {/* Not called "reconciliation" any more. Nothing external enters
                this table — expected is our own day ledger's opinion — so a
                provider over-billing us cannot appear in it. The bill drawer
                does the reconciling, against their document. Two tabs with
                the same name taught the office to trust neither. */}
            <h2 className="font-semibold text-slate-700">Collection by rider</h2>
            <p className="text-xs text-slate-500">
              What these vehicles cost us over the range against what we got back.
              &quot;Settled via&quot; is the company payout that actually collected the rent.
              To check the provider&apos;s own bill, open it below.
            </p>
          </div>
          <button onClick={downloadRecon}
                  className="text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white px-3 py-1.5 rounded">
            Export for boss (.xlsx)
          </button>
        </div>
        <div className="overflow-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50">
              <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-3 py-2">Rider</th>
                <th className="px-3 py-2">EV(s)</th>
                <th className="px-3 py-2 text-right">Cost to us</th>
                <th className="px-3 py-2 text-right">Expected</th>
                <th className="px-3 py-2 text-right">Collected</th>
                <th className="px-3 py-2 text-right">Missed</th>
                <th className="px-3 py-2 text-right">Pending</th>
                <th className="px-3 py-2 text-right" title="Collected against what we asked the rider for">Collected %</th>
                <th className="px-3 py-2 text-right" title="Collected against what the vehicle cost us">Recovered %</th>
                <th className="px-3 py-2">Settled via</th>
              </tr>
            </thead>
            <tbody>
              {(recon?.rows || []).map(r => (
                <tr key={r.person_id} className="border-t hover:bg-slate-50">
                  <td className="px-3 py-2">{r.name}</td>
                  <td className="px-3 py-2 text-xs text-slate-600">{r.ev_ids}</td>
                  <td className="px-3 py-2 text-right text-slate-500">₹{fmt(r.provider_owed)}</td>
                  <td className="px-3 py-2 text-right">₹{fmt(r.expected)}</td>
                  <td className="px-3 py-2 text-right text-emerald-300">₹{fmt(r.collected)}</td>
                  <td className="px-3 py-2 text-right text-red-400">₹{fmt(r.missed)}</td>
                  <td className="px-3 py-2 text-right text-amber-400">₹{fmt(r.pending)}</td>
                  <td className="px-3 py-2 text-right">{r.collection_pct}%</td>
                  <td className={'px-3 py-2 text-right ' +
                        (r.recovery_pct >= 95 ? 'text-emerald-300'
                         : r.recovery_pct >= 70 ? 'text-amber-400' : 'text-red-400')}>
                    {r.recovery_pct}%
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-600">{r.settled_via || '—'}</td>
                </tr>
              ))}
              {/* The days nobody was billed for. Money we owed and could not
                  charge anybody, and the single largest class of dispute in
                  the week-36 bill — the old table dropped every one of them. */}
              {(recon?.unheld || []).map(u => (
                <tr key={'unheld:' + u.ev_id} className="border-t bg-orange-500/[0.04]">
                  <td className="px-3 py-2 text-orange-300 text-xs">nobody · {u.status}</td>
                  <td className="px-3 py-2 text-xs text-slate-600">{u.ev_id}</td>
                  <td className="px-3 py-2 text-right text-orange-300">₹{fmt(u.provider_owed)}</td>
                  <td className="px-3 py-2 text-right text-slate-500" colSpan={6}>
                    {u.days} day{u.days === 1 ? '' : 's'} we owed for and billed nobody
                  </td>
                  <td className="px-3 py-2"></td>
                </tr>
              ))}
              {recon && recon.rows.length > 0 && (
                <tr className="border-t bg-slate-50 font-semibold">
                  <td className="px-3 py-2" colSpan={2}>TOTAL ({recon.totals.rider_count})</td>
                  <td className="px-3 py-2 text-right">
                    ₹{fmt(recon.totals.provider_owed + recon.totals.unheld_owed)}
                  </td>
                  <td className="px-3 py-2 text-right">₹{fmt(recon.totals.expected)}</td>
                  <td className="px-3 py-2 text-right text-emerald-300">₹{fmt(recon.totals.collected)}</td>
                  <td className="px-3 py-2 text-right text-red-400">₹{fmt(recon.totals.missed)}</td>
                  <td className="px-3 py-2 text-right text-amber-400">₹{fmt(recon.totals.pending)}</td>
                  <td className="px-3 py-2 text-right">{recon.totals.collection_pct}%</td>
                  <td className="px-3 py-2 text-right">{recon.totals.recovery_pct}%</td>
                  <td className="px-3 py-2"></td>
                </tr>
              )}
              {!loadingRecon && (!recon || recon.rows.length === 0) && (
                <tr><td colSpan={10} className="px-3 py-8 text-center text-slate-400">
                  No rider rent activity in this range.
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Bills history */}
      <section className="panel overflow-hidden">
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
        <div className="fixed inset-0 bg-black/60 backdrop-blur-[2px] z-40 flex justify-end"
             onClick={() => { setOpenBill(null); setBillDetail(null); setBillRecon(null) }}>
          <div className="bg-panel w-full max-w-3xl h-full overflow-auto shadow-xl"
               onClick={e => e.stopPropagation()}>
            <div className="p-4 border-b sticky top-0 bg-panel flex items-center justify-between">
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
                          className="text-xs text-rose-400 underline">Delete</button>
                )}
                <button onClick={() => { setOpenBill(null); setBillDetail(null); setBillRecon(null) }}
                        className="text-slate-400 hover:text-slate-600">✕</button>
              </div>
            </div>
            <div className="px-4 pt-3 flex items-center gap-2">
              {(['recon', 'tally'] as const).map(v => (
                <button key={v} onClick={() => setBillView(v)}
                        className={'text-xs px-2 py-1 rounded border ' + (billView === v
                          ? 'bg-indigo-500/15 text-indigo-300 border-indigo-500/30'
                          : 'text-slate-400 border-slate-700 hover:text-slate-200')}>
                  {v === 'recon' ? 'Reconciliation' : 'Their total vs ours'}
                </button>
              ))}
              {billView === 'recon' && billRecon && (
                <button onClick={() => downloadBillRecon(openBill)}
                        className="ml-auto text-xs text-indigo-600 underline">Export .xlsx</button>
              )}
            </div>
            {billView === 'recon'
              ? (reconBusy || !billRecon
                  ? <div className="p-8 flex justify-center"><Spinner /></div>
                  : <BillRecon recon={billRecon}
                               onOverride={(ev, f, v) => setOverride(openBill, ev, f, v)} />)
              : (!billDetail
                  ? <div className="p-8 flex justify-center"><Spinner /></div>
                  : <BillTally lines={billDetail.lines} billTotal={billDetail.bill.bill_total} />)}
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
    indigo:  'bg-indigo-500/10 text-indigo-300',
    emerald: 'bg-emerald-500/10 text-emerald-300',
    amber:   'bg-amber-500/10 text-amber-300',
    sky:     'bg-sky-500/10 text-sky-300',
    rose:    'bg-rose-500/10 text-rose-300',
  }
  return (
    <div className={'rounded-lg p-3 border ' + (map[tone] || 'bg-panel')}>
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
        <div>⚠️ Discrepancy: <b className="text-amber-300">{discrepancy.length}</b></div>
        <div>🚫 Not in our ledger: <b className="text-rose-300">{notInLedger.length}</b></div>
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
                ? 'bg-rose-500/10'
                : matched ? '' : 'bg-amber-500/10'
              return (
                <tr key={l.id} className={'border-t ' + tone}>
                  <td className="px-3 py-2 text-slate-500 text-xs">{l.line_no}</td>
                  <td className="px-3 py-2 font-mono text-xs">{l.ev_id_raw || '—'}</td>
                  <td className="px-3 py-2 text-right">₹{fmt(l.their_amount)}</td>
                  <td className="px-3 py-2 text-right">
                    {l.our_amount === null ? <span className="text-rose-400">—</span> : `₹${fmt(l.our_amount)}`}
                  </td>
                  <td className={'px-3 py-2 text-right ' +
                                  (d === null ? 'text-slate-400'
                                  : Math.abs(d) < 0.5 ? 'text-emerald-300'
                                  : 'text-amber-300 font-semibold')}>
                    {d === null ? '—' : `${d >= 0 ? '+' : ''}₹${fmt(d)}`}
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-600">{l.status_note || '—'}</td>
                  <td className="px-3 py-2 text-xs">
                    {l.our_amount === null
                      ? <span className="text-rose-300">Not in ledger</span>
                      : matched
                        ? <span className="text-emerald-300">Matched</span>
                        : <span className="text-amber-300">Discrepancy</span>}
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

/**
 * A provider bill against our own books, line by line.
 *
 * The Tag column comes second on purpose: the office reads it down the page
 * and hands the page to somebody else, so it is the thing that has to be
 * legible at a glance. Everything the tag no longer carries — which vehicle
 * the rider is really on, whose name the provider used, what was cleared by
 * hand — sits in Notes at the far right.
 *
 * Every tag is editable, because most of what gets corrected here is not in
 * the database at all: which vehicles actually came back, which rider is
 * really on a unit, that two person records are one man. The server keys the
 * correction to the vehicle, so it carries into next week's bill.
 */
function BillRecon({ recon, onOverride }: {
  recon: BillReconResp
  onOverride: (evId: string, field: string, value: string | null) => void
}) {
  const [tag, setTag] = useState<string>('all')
  const t = recon.totals
  const rows = tag === 'all' ? recon.rows : recon.rows.filter(r => r.tag === tag)
  const counts = recon.tag_counts || {}

  return (
    <div className="p-4 space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <Card label="They billed" value={`₹${fmt(t.billed || 0)}`} tone="indigo"
              sub={t.damage ? `incl. ₹${fmt(t.damage)} damage` : undefined} />
        <Card label="Expected at our rate" value={`₹${fmt(t.expected || 0)}`} tone="sky" />
        <Card label="Collected" value={`₹${fmt(t.collected || 0)}`} tone="emerald"
              sub={`of ₹${fmt(t.charged || 0)} charged`} />
        <Card label="Still owed" value={`₹${fmt(t.missed || 0)}`}
              tone={(t.missed || 0) > 0 ? 'rose' : 'emerald'} />
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <button onClick={() => setTag('all')}
                className={'text-xs px-2 py-0.5 rounded border ' + (tag === 'all'
                  ? 'bg-slate-500/15 text-slate-200 border-slate-500/30'
                  : 'text-slate-400 border-slate-700')}>
          All {recon.rows.length}
        </button>
        {Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([k, n]) => (
          <button key={k} onClick={() => setTag(tag === k ? 'all' : k)}
                  className={'text-xs px-2 py-0.5 rounded border ' +
                    (tag === k ? TAG_TONE[k] || 'border-slate-500' : 'text-slate-400 border-slate-700')}>
            {k} {n}
          </button>
        ))}
      </div>

      <div className="border rounded overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
              <th className="px-3 py-2">EV</th>
              <th className="px-3 py-2">Tag</th>
              <th className="px-3 py-2">Rider</th>
              <th className="px-3 py-2 text-right">Days</th>
              <th className="px-3 py-2 text-right">Billed</th>
              <th className="px-3 py-2 text-right">Expected</th>
              <th className="px-3 py-2 text-right">Charged</th>
              <th className="px-3 py-2 text-right">Collected</th>
              <th className="px-3 py-2 text-right">Owed</th>
              <th className="px-3 py-2">Notes</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.ev_id + ':' + r.tag} className="border-t align-top">
                <td className="px-3 py-2 font-mono text-xs whitespace-nowrap">{r.ev_id}</td>
                <td className="px-3 py-2">
                  <select
                    value={r.tag}
                    onChange={e => onOverride(r.ev_id, 'tag', e.target.value)}
                    title={r.overridden?.includes('tag') ? 'Corrected by hand' : 'Derived'}
                    className={'text-xs rounded border px-1.5 py-0.5 bg-transparent ' +
                      (TAG_TONE[r.tag] || 'border-slate-600') +
                      (r.overridden?.includes('tag') ? ' font-semibold' : '')}
                  >
                    {recon.tags.map(tg => <option key={tg} value={tg}>{tg}</option>)}
                  </select>
                </td>
                <td className="px-3 py-2">
                  {r.rider || <span className="text-slate-400">—</span>}
                  {r.provider_name && r.rider && r.provider_name.toLowerCase() !== r.rider.toLowerCase() && (
                    <div className="text-[10px] text-slate-400">they say {r.provider_name}</div>
                  )}
                </td>
                <td className="px-3 py-2 text-right text-xs">{r.days || ''}</td>
                <td className="px-3 py-2 text-right">₹{fmt(r.billed)}</td>
                <td className="px-3 py-2 text-right">{r.expected ? '₹' + fmt(r.expected) : '–'}</td>
                <td className="px-3 py-2 text-right">{r.charged ? '₹' + fmt(r.charged) : '–'}</td>
                <td className="px-3 py-2 text-right text-emerald-300">
                  {r.collected ? '₹' + fmt(r.collected) : '–'}
                </td>
                <td className="px-3 py-2 text-right text-rose-300">
                  {r.missed ? '₹' + fmt(r.missed) : '–'}
                </td>
                <td className="px-3 py-2 text-xs text-slate-500 max-w-xs">{r.note}</td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={10} className="px-3 py-8 text-center text-slate-400">
                Nothing tagged {tag}.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
