import { FormEvent, useEffect, useState } from 'react'
import { usePersistedState } from '../state/usePersistedState'
import { api } from '../api/client'
import { Spinner } from '../components/Spinner'
import { addDaysISO, todayISO } from '../lib/dates'
import { money as fmt } from '../lib/format'
import type { Company, CycleResult, InactiveRow, RiderOut, RiderResultRow, RunResponse, SalaryLine } from '../api/types'

const isoToday = (offset = 0) => addDaysISO(todayISO(), offset)

/** What a preview was run for. Commit is only offered for an identical set.
 *  A payout-file company is keyed on the file; a per-order company on the
 *  exact order counts typed (so editing a count re-requires a preview). */
interface RunKey { company: string; cycleStart: string; cycleEnd: string; input: string }
const fileKey = (f: File) => `file:${f.name}:${f.size}:${f.lastModified}`
const ordersKey = (o: Record<string, string>) =>
  'orders:' + Object.entries(o).filter(([, v]) => v !== '').sort().map(([k, v]) => `${k}=${v}`).join(',')
/** Salary companies: rider_id -> {days present, orders} typed or uploaded. */
type Attendance = Record<string, { days: string; orders: string }>
const attendanceKey = (a: Attendance, salaries: Record<string, string>) =>
  'att:' + Object.entries(a).filter(([, v]) => v.days !== '' || v.orders !== '').sort()
    .map(([k, v]) => `${k}=${v.days}/${v.orders}/${salaries[k] ?? ''}`).join(',')
const sameKey = (a: RunKey | null, b: RunKey) =>
  !!a && a.company === b.company && a.cycleStart === b.cycleStart && a.cycleEnd === b.cycleEnd &&
  a.input === b.input

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
  // Which company you process is a sticky choice — coming back to this page
  // mid-task should not reset it. Dates deliberately stay ephemeral: they
  // re-derive from the company's next unprocessed cycle on every visit.
  const [company, setCompany] = usePersistedState('process:company', '')
  const [cycleStart, setCycleStart] = useState(isoToday(-7))
  const [cycleEnd, setCycleEnd] = useState(isoToday(-1))
  const [file, setFile] = useState<File | null>(null)
  // Per-order companies: rider_id -> order count typed off their dashboard.
  const [orders, setOrders] = useState<Record<string, string>>({})
  const [orderRiders, setOrderRiders] = useState<RiderOut[]>([])
  const [attendance, setAttendance] = useState<Attendance>({})
  // Salary per rider (rupees per cycle) as shown in the table; saved to the
  // rider row on blur so it is remembered next cycle.
  const [salaries, setSalaries] = useState<Record<string, string>>({})
  const [salaryLines, setSalaryLines] = useState<SalaryLine[] | null>(null)
  const [sheetNote, setSheetNote] = useState<string | null>(null)
  const [preview, setPreview] = useState<CycleResult | null>(null)
  const [busy, setBusy] = useState<'preview' | 'commit' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [onboardOpen, setOnboardOpen] = useState(false)
  // The inputs the last successful preview was run with. Commit writes the
  // ledger irreversibly, so it is enabled only when a preview of exactly these
  // inputs has been seen (and confirmed) — it used to be one click from a
  // fresh file pick.
  const [previewedKey, setPreviewedKey] = useState<RunKey | null>(null)
  const selected = companies.find((c) => c.company_name === company)
  const perOrder = selected?.payment_model === 'per_order'
  const salaried = selected?.payment_model === 'salary'
  const typed = perOrder || salaried
  const rate = selected?.per_order_rate ?? 0
  const ordersFilled = Object.values(orders).some((v) => v !== '')
  const attendanceFilled = Object.values(attendance).some((v) => v.days !== '' || v.orders !== '')
  const totalOrders = Object.values(orders).reduce((a, v) => a + (Number(v) || 0), 0)
  const hasInput = perOrder ? ordersFilled : salaried ? attendanceFilled : !!file
  const currentKey: RunKey | null = hasInput
    ? { company, cycleStart, cycleEnd,
        input: perOrder ? ordersKey(orders) : salaried ? attendanceKey(attendance, salaries) : fileKey(file as File) }
    : null
  const previewIsCurrent = !!currentKey && sameKey(previewedKey, currentKey)
  const blockers: string[] = []
  if (preview?.unreadable_riders?.length)
    blockers.push(`${preview.unreadable_riders.length} rider(s) have an unreadable payout cell`)
  if (preview?.unknown_riders?.length)
    blockers.push(`${preview.unknown_riders.length} unknown rider(s) not onboarded`)
  const canCommit = hasInput && !busy && previewIsCurrent && !preview?.committed && blockers.length === 0

  useEffect(() => {
    api
      .get<Company[]>('/companies')
      .then((cs) => {
        // Direct-pay companies have nothing to process — they never appear here.
        const active = cs.filter((c) => c.is_active && c.payment_model !== 'direct')
        setCompanies(active)
        if (active.length) {
          setCompany((cur) => (active.some((c) => c.company_name === cur) ? cur : active[0].company_name))
        }
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

  // Per-order company: load its active riders so the counts can be typed
  // against names, not bare ids. Counts reset when the company changes.
  useEffect(() => {
    setOrders({}); setAttendance({}); setSalaries({}); setSalaryLines(null); setSheetNote(null)
    setOrderRiders([]); setPreview(null); setPreviewedKey(null)
    if (!company || !typed) return
    api.get<RiderOut[]>('/riders?company=' + encodeURIComponent(company) + '&active=true')
      .then((rs) => {
        const sorted = [...rs].sort((a, b) => (a.name ?? '').localeCompare(b.name ?? ''))
        setOrderRiders(sorted)
        setSalaries(Object.fromEntries(sorted.map((r) => [r.rider_id, r.salary != null ? String(r.salary) : ''])))
      })
      .catch((e: Error) => setError(e.message))
  }, [company, typed])

  async function saveSalary(rid: string, value: string) {
    const r = orderRiders.find((x) => x.rider_id === rid)
    const current = r?.salary != null ? String(r.salary) : ''
    if (value === current || value === '') return
    try {
      const saved = await api.patch<RiderOut>('/riders/' + encodeURIComponent(rid) + '?company=' + encodeURIComponent(company), { salary: Number(value) })
      setOrderRiders((cur) => cur.map((x) => (x.rider_id === rid ? { ...x, salary: saved.salary } : x)))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save salary')
    }
  }

  async function uploadSheet(f: File | null) {
    if (!f || !company) return
    setSheetNote(null); setError(null)
    const form = new FormData()
    form.set('company', company)
    form.set('file', f)
    try {
      const r = await api.postForm<{ rows: { rider_id: string; days_present: number | null; orders: number | null }[]; unknown: { rider_id: string; name: string | null }[]; matched: Record<string, string | null> }>('/cycles/parse-sheet', form)
      if (perOrder) {
        setOrders((cur) => ({ ...cur, ...Object.fromEntries(r.rows.map((x) => [x.rider_id, x.orders != null ? String(x.orders) : (cur[x.rider_id] ?? '')])) }))
      } else {
        setAttendance((cur) => ({ ...cur, ...Object.fromEntries(r.rows.map((x) => [x.rider_id, {
          days: x.days_present != null ? String(x.days_present) : (cur[x.rider_id]?.days ?? ''),
          orders: x.orders != null ? String(x.orders) : (cur[x.rider_id]?.orders ?? ''),
        }])) }))
      }
      const parts = [`${r.rows.length} rider(s) filled in from the sheet`]
      if (!r.matched.days_present && salaried) parts.push('no "days present" column found')
      if (!r.matched.orders) parts.push('no "orders" column found')
      if (r.unknown.length) parts.push(`${r.unknown.length} id(s) not on the roster: ${r.unknown.slice(0, 6).map((u) => u.rider_id).join(', ')}${r.unknown.length > 6 ? '…' : ''}`)
      setSheetNote(parts.join(' · '))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not read the sheet')
    }
  }

  async function submit(commit: boolean, e?: FormEvent) {
    e?.preventDefault()
    if (!hasInput || !company || !currentKey) return
    const key = currentKey
    if (commit) {
      if (!sameKey(previewedKey, key)) {
        setError('Run a preview of this exact file and cycle before committing.')
        return
      }
      const t = preview?.totals ?? {}
      const ok = window.confirm(
        `Commit ${company} ${cycleStart} → ${cycleEnd}?\n\n` +
        `${t.riders_paid ?? 0} riders paid · ₹${fmt(t.total_release ?? 0)} released · ` +
        `₹${fmt(t.total_rent_charged ?? 0)} rent charged.\n\nThis writes the ledger and cannot be undone.`,
      )
      if (!ok) return
    }
    setBusy(commit ? 'commit' : 'preview')
    setError(null)
    try {
      const form = new FormData()
      form.set('company', company)
      form.set('cycle_start', cycleStart)
      form.set('cycle_end', cycleEnd)
      form.set('commit', commit ? 'true' : 'false')
      if (perOrder) {
        form.set('orders', JSON.stringify(
          Object.entries(orders).filter(([, v]) => v !== '').map(([rider_id, v]) => ({ rider_id, orders: Number(v) })),
        ))
      } else if (salaried) {
        form.set('attendance', JSON.stringify(
          Object.entries(attendance).filter(([, v]) => v.days !== '' || v.orders !== '')
            .map(([rider_id, v]) => ({ rider_id, days_present: Number(v.days) || 0, orders: Number(v.orders) || 0 })),
        ))
      } else {
        form.set('file', file as File)
      }
      const r = await api.postForm<RunResponse>('/cycles/run', form)
      setPreview(r.result)
      setSalaryLines(r.salary_lines ?? null)
      setPreviewedKey(key)
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
        {perOrder
          ? <>{company} sends no file — type each rider's order count from their dashboard; we pay ₹{rate} an order, deduct rent as usual and release the rest. Preview, then commit.</>
          : salaried
          ? <>{company} riders are salaried — mark each rider's days present and orders (or upload the sheet you keep). Pay = salary less a day's pay per day short of {selected?.salary_expected_days ?? 26}, plus ₹{selected?.incentive_per_order ?? 0} an order and ₹{selected?.incentive_per_day ?? 0} a day present; EV rent comes off as usual. Preview, then commit.</>
          : <>Upload a company payout file, preview the result, then commit when ready.
            Commit writes everything atomically and returns the styled workbook for download.</>}
        <span className="text-slate-400"> Companies that pay riders directly are not listed — there is nothing to process for them.</span>
      </p>

      <form onSubmit={(e) => submit(false, e)} className="panel p-6 mb-6">
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
          {perOrder ? (
            <div>
              <label className="block text-sm font-medium mb-1">Payout</label>
              <div className="text-sm text-slate-600 py-2">
                ₹{rate} per order × <b>{totalOrders}</b> orders = <b>₹{fmt(rate * totalOrders)}</b>
              </div>
            </div>
          ) : salaried ? (
            <div>
              <label className="block text-sm font-medium mb-1">Attendance sheet (optional)</label>
              <input type="file" accept=".xlsx,.xls,.csv" className="w-full text-sm"
                     onChange={(e) => { void uploadSheet(e.target.files?.[0] ?? null); e.target.value = '' }} />
              <div className="text-[11px] text-slate-500 mt-1">Columns: rider id, days present, orders — fills the table below.</div>
            </div>
          ) : (
            <div>
              <label className="block text-sm font-medium mb-1">Payout File (.xlsx)</label>
              <input
                type="file" accept=".xlsx"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="w-full text-sm"
              />
            </div>
          )}
        </div>
        {perOrder && (
          <>
            <OrdersTable riders={orderRiders} orders={orders} rate={rate} company={company}
                         onChange={(rid, v) => setOrders((cur) => ({ ...cur, [rid]: v }))} />
            <label className="inline-block text-xs text-slate-500 mt-2">
              or fill the counts from a sheet:{' '}
              <input type="file" accept=".xlsx,.xls,.csv" className="text-xs"
                     onChange={(e) => { void uploadSheet(e.target.files?.[0] ?? null); e.target.value = '' }} />
            </label>
          </>
        )}
        {salaried && selected && (
          <SalaryTable riders={orderRiders} attendance={attendance} salaries={salaries} company={company}
                       expectedDays={selected.salary_expected_days ?? 26}
                       incOrder={selected.incentive_per_order ?? 0} incDay={selected.incentive_per_day ?? 0}
                       onAttendance={(rid, patch) => setAttendance((cur) => ({ ...cur, [rid]: { ...(cur[rid] ?? { days: '', orders: '' }), ...patch } }))}
                       onSalary={(rid, v) => setSalaries((cur) => ({ ...cur, [rid]: v }))}
                       onSalaryBlur={(rid, v) => void saveSalary(rid, v)} />
        )}
        {sheetNote && <p className="text-xs text-slate-500 mt-2">{sheetNote}</p>}
        <div className="flex flex-wrap gap-3 mt-4 items-center">
          <button
            type="submit" disabled={!hasInput || !!busy}
            className="bg-slate-200 hover:bg-slate-300 px-4 py-2 rounded font-medium disabled:opacity-50"
          >
            {busy === 'preview' ? 'Previewing...' : 'Preview (dry run)'}
          </button>
          <button
            type="button" onClick={() => void submit(true)} disabled={!canCommit}
            title={
              !hasInput ? (perOrder ? 'Enter the order counts first' : 'Choose a file first')
              : !previewIsCurrent ? 'Preview this exact file and cycle first'
              : blockers.length ? blockers.join('; ')
              : preview?.committed ? 'Already committed'
              : 'Write the ledger and download the workbook'
            }
            className="bg-brand hover:bg-brand-700 text-white px-4 py-2 rounded font-medium disabled:opacity-50"
          >
            {busy === 'commit' ? 'Committing...' : 'Commit & Download'}
          </button>
          {busy && <Spinner />}
          {hasInput && !previewIsCurrent && !busy && (
            <span className="text-xs text-slate-500">
              Preview first — commit unlocks for the previewed {typed ? 'entries' : 'file'} and dates.
            </span>
          )}
          {previewIsCurrent && blockers.length > 0 && (
            <span className="text-xs text-rose-300">Cannot commit: {blockers.join('; ')}.</span>
          )}
        </div>
        {error && <p className="text-red-400 mt-3 text-sm">{error}</p>}
      </form>

      {preview && salaryLines && salaryLines.length > 0 && (
        <div className="panel p-6 mb-6">
          <h2 className="font-semibold mb-2">Salary working — {preview.company} {preview.cycle_start} → {preview.cycle_end}</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left border-b border-edge-soft">
                <tr>
                  <th className="px-3 py-2 font-medium text-xs">Rider</th>
                  <th className="px-3 py-2 font-medium text-xs text-right">Salary</th>
                  <th className="px-3 py-2 font-medium text-xs text-right">Present</th>
                  <th className="px-3 py-2 font-medium text-xs text-right">Days off</th>
                  <th className="px-3 py-2 font-medium text-xs text-right">Base pay</th>
                  <th className="px-3 py-2 font-medium text-xs text-right">Orders</th>
                  <th className="px-3 py-2 font-medium text-xs text-right">Incentives</th>
                  <th className="px-3 py-2 font-medium text-xs text-right">Gross</th>
                </tr>
              </thead>
              <tbody>
                {salaryLines.map((l) => (
                  <tr key={l.rider_id} className="border-t border-edge-soft">
                    <td className="px-3 py-1.5">{l.name || l.rider_id} <span className="text-slate-500 text-xs">{l.rider_id}</span></td>
                    <td className="px-3 py-1.5 text-right tabular-nums">₹{fmt(l.salary)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{l.days_present}</td>
                    <td className={'px-3 py-1.5 text-right tabular-nums' + (l.days_off > 0 ? ' text-amber-300' : '')}>{l.days_off}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">₹{fmt(l.base_pay)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{l.orders}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">₹{fmt(l.incentives)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums font-semibold">₹{fmt(l.payout)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-[11px] text-slate-500 mt-2">Gross is what goes into the cycle below; EV rent and dues come off it there.</p>
        </div>
      )}

      {preview && (
        <div className="panel p-6">
          <div className="flex items-baseline gap-3 mb-4 flex-wrap">
            <h2 className="text-xl font-bold">
              {preview.committed ? 'Committed' : 'Preview'} — {preview.company} cycle {preview.cycle_start} → {preview.cycle_end}
            </h2>
            <span className={'text-xs px-2 py-0.5 rounded ' + (preview.committed ? 'bg-emerald-500/20' : 'bg-slate-200')}>
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

          {preview.unreadable_riders && preview.unreadable_riders.length > 0 && (
            <div className="mb-4 bg-rose-500/10 border border-rose-400/30 rounded p-3">
              <p className="font-medium text-rose-200">
                {preview.unreadable_riders.length} rider(s) have a payout cell that is not a number.
              </p>
              <p className="text-xs text-rose-300 mt-1">
                They are kept as present (no missed-rent arrears), but nothing can be settled from
                an unreadable amount. Fix the cells in the file and upload it again.
              </p>
              <ul className="mt-2 text-sm text-rose-200 list-disc list-inside">
                {preview.unreadable_riders.map((u) => (
                  <li key={u.rider_id}>
                    <span className="font-mono">{u.rider_id}</span>{u.name ? ` — ${u.name}` : ''}:
                    {' '}<span className="font-mono bg-rose-500/15 px-1 rounded">{u.cell || '(blank)'}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {preview.auto_linked && preview.auto_linked.length > 0 && (
            <details className="mb-4 bg-sky-500/10 border border-sky-400/30 rounded p-3">
              <summary className="font-medium cursor-pointer text-sky-200">
                {preview.auto_linked.length} rider(s) linked from {preview.auto_linked[0].linked_from} by shared rider ID
              </summary>
              <ul className="mt-2 text-sm text-sky-200 list-disc list-inside">
                {preview.auto_linked.map((a) => (
                  <li key={a.rider_id}><span className="font-mono">{a.rider_id}</span> → {a.name} (person #{a.person_id})</li>
                ))}
              </ul>
            </details>
          )}

          {preview.unknown_riders && preview.unknown_riders.length > 0 && (
            <div className="mb-4 bg-rose-500/10 border border-rose-400/30 rounded p-3 flex items-start justify-between gap-3">
              <div>
                <p className="font-medium text-rose-200">
                  {preview.unknown_riders.length} rider(s) in the file aren't in the database yet.
                </p>
                <p className="text-xs text-rose-300 mt-1">
                  Onboard them now (add or link to an existing person) so they
                  get included when you commit. The list will pre-fill from the
                  file's name and hub columns.
                </p>
              </div>
              <button onClick={() => setOnboardOpen(true)}
                      className="text-sm bg-rose-600 hover:bg-rose-700 text-white px-3 py-1.5 rounded whitespace-nowrap">
                Onboard riders…
              </button>
            </div>
          )}

          {preview.warnings.length > 0 && (
            <details className="mb-4 bg-amber-500/10 border border-amber-400/30 rounded p-3">
              <summary className="font-medium cursor-pointer">
                {preview.warnings.length} warning(s)
              </summary>
              <ul className="mt-2 text-sm list-disc list-inside text-amber-200">
                {preview.warnings.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            </details>
          )}

          {onboardOpen && preview && (
            <OnboardUnknownsModal
              company={preview.company}
              unknowns={preview.unknown_riders ?? []}
              onClose={() => setOnboardOpen(false)}
              onDone={() => { setOnboardOpen(false); void submit(false) }}
            />
          )}

          <Section title={`PAY (${preview.pay_rows.length})`} color="bg-emerald-500/15">
            <PayTable rows={preview.pay_rows} />
          </Section>
          {preview.dues_rows.length > 0 && (
            <Section title={`DUES (${preview.dues_rows.length})`} color="bg-orange-500/15">
              <PayTable rows={preview.dues_rows} />
            </Section>
          )}
          {preview.inactive_rows.length > 0 && (
            <Section title={`INACTIVE (${preview.inactive_rows.length})`} color="bg-red-500/15">
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
            <tr key={r.rider_id + ':' + r.company} className={'border-t ' + (r.is_hold ? 'bg-amber-500/15' : '')}>
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

interface OnboardRow {
  rider_id: string
  action: 'create' | 'link'
  name: string
  hub: string
  account_no: string
  ifsc: string
  vehicle: string
  link_to_rider_id: string
  link_to_person_id: string
  payout: number
}

function OnboardUnknownsModal({ company, unknowns, onClose, onDone }: {
  company: string
  unknowns: { rider_id: string; name: string; hub: string; payout: number }[]
  onClose: () => void
  onDone: () => void
}) {
  const [rows, setRows] = useState<OnboardRow[]>(
    unknowns.map((u) => ({
      rider_id: u.rider_id,
      action: 'create',
      name: u.name ?? '',
      hub: u.hub ?? '',
      account_no: '',
      ifsc: '',
      vehicle: 'BIKE',
      link_to_rider_id: '',
      link_to_person_id: '',
      payout: u.payout,
    })),
  )
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [tone, setTone] = useState<'ok' | 'err'>('ok')

  function update(i: number, patch: Partial<OnboardRow>) {
    setRows((rs) => rs.map((r, idx) => (idx === i ? { ...r, ...patch } : r)))
  }

  async function submit() {
    setBusy(true); setMsg(null)
    try {
      const body = {
        company,
        rows: rows.map((r) => {
          const out: Record<string, unknown> = {
            rider_id: r.rider_id, action: r.action,
            name: r.name, hub: r.hub,
            account_no: r.account_no || null, ifsc: r.ifsc || null,
            vehicle: r.vehicle || 'BIKE',
          }
          if (r.action === 'link') {
            if (r.link_to_person_id) out.link_to_person_id = parseInt(r.link_to_person_id)
            if (r.link_to_rider_id)  out.link_to_rider_id  = r.link_to_rider_id
          }
          return out
        }),
      }
      const r = await api.post<{
        committed: boolean
        summary: { created: number; linked: number; errors: number }
        errors: string[]
      }>('/riders/onboard-unknowns', body)
      if (!r.committed) {
        setTone('err')
        setMsg(`Failed — ${r.errors.join('; ')}`)
        return
      }
      setTone('ok')
      setMsg(`Onboarded — created ${r.summary.created}, linked ${r.summary.linked}.`)
      // Brief delay so the operator sees the success message before re-preview.
      setTimeout(onDone, 400)
    } catch (e) {
      setTone('err'); setMsg(e instanceof Error ? e.message : 'Failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-[2px] flex items-center justify-center p-4 z-50">
      <div className="panel-pop w-full max-w-6xl max-h-[90vh] flex flex-col">
        <div className="px-5 py-3 border-b flex items-start justify-between gap-3">
          <div>
            <h3 className="font-semibold">Onboard unknown riders — {company}</h3>
            <p className="text-xs text-slate-500">
              For each row, choose <b>Create</b> (new person) or <b>Link</b>
              (attach this rider_id to someone already in the database). All
              rows commit in one transaction — any error rolls everything back.
            </p>
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-700">✕</button>
        </div>

        <div className="px-3 py-3 overflow-auto">
          <table className="w-full text-xs">
            <thead className="bg-slate-100 text-left">
              <tr>
                <th className="px-2 py-1">Rider ID</th>
                <th className="px-2 py-1">Action</th>
                <th className="px-2 py-1">Name</th>
                <th className="px-2 py-1">Hub</th>
                <th className="px-2 py-1">Vehicle</th>
                <th className="px-2 py-1">Account #</th>
                <th className="px-2 py-1">IFSC</th>
                <th className="px-2 py-1">Link target</th>
                <th className="px-2 py-1 text-right">Payout</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={r.rider_id} className="border-t align-top">
                  <td className="px-2 py-1 font-mono">{r.rider_id}</td>
                  <td className="px-2 py-1">
                    <select value={r.action}
                            onChange={(e) => update(i, { action: e.target.value as 'create' | 'link' })}
                            className="border rounded px-1 py-0.5 text-xs">
                      <option value="create">Create</option>
                      <option value="link">Link to existing</option>
                    </select>
                  </td>
                  <td className="px-2 py-1">
                    <input value={r.name} onChange={(e) => update(i, { name: e.target.value })}
                           disabled={r.action === 'link' && (!!r.link_to_person_id || !!r.link_to_rider_id)}
                           className="border rounded px-1 py-0.5 text-xs w-32 disabled:bg-slate-50" />
                  </td>
                  <td className="px-2 py-1">
                    <input value={r.hub} onChange={(e) => update(i, { hub: e.target.value })}
                           className="border rounded px-1 py-0.5 text-xs w-24" />
                  </td>
                  <td className="px-2 py-1">
                    <select value={r.vehicle}
                            onChange={(e) => update(i, { vehicle: e.target.value })}
                            className="border rounded px-1 py-0.5 text-xs">
                      <option value="BIKE">BIKE</option>
                      <option value="EV">EV</option>
                      <option value="OTHER">OTHER</option>
                    </select>
                  </td>
                  <td className="px-2 py-1">
                    <input value={r.account_no}
                           onChange={(e) => update(i, { account_no: e.target.value })}
                           className="border rounded px-1 py-0.5 text-xs w-28" />
                  </td>
                  <td className="px-2 py-1">
                    <input value={r.ifsc}
                           onChange={(e) => update(i, { ifsc: e.target.value.toUpperCase() })}
                           className="border rounded px-1 py-0.5 text-xs w-24" />
                  </td>
                  <td className="px-2 py-1">
                    {r.action === 'link' ? (
                      <div className="flex flex-col gap-1">
                        <input value={r.link_to_person_id} placeholder="person ID"
                               onChange={(e) => update(i, { link_to_person_id: e.target.value })}
                               className="border rounded px-1 py-0.5 text-xs w-24" />
                        <input value={r.link_to_rider_id} placeholder="or rider ID"
                               onChange={(e) => update(i, { link_to_rider_id: e.target.value })}
                               className="border rounded px-1 py-0.5 text-xs w-28" />
                      </div>
                    ) : <span className="text-slate-400 text-[10px]">n/a</span>}
                  </td>
                  <td className="px-2 py-1 text-right">{fmt(r.payout)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="px-5 py-3 border-t flex justify-end items-center gap-2">
          {msg && (
            <span className={'text-xs ' + (tone === 'err' ? 'text-red-400' : 'text-emerald-300')}>
              {msg}
            </span>
          )}
          <button onClick={onClose} disabled={busy}
                  className="text-sm px-3 py-1.5 rounded bg-slate-200 hover:bg-slate-300">
            Cancel
          </button>
          <button onClick={submit} disabled={busy}
                  className="text-sm px-3 py-1.5 rounded bg-rose-600 hover:bg-rose-700 text-white disabled:opacity-50">
            {busy ? 'Onboarding…' : `Onboard ${rows.length} & re-preview`}
          </button>
        </div>
      </div>
    </div>
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
          <tr key={r.person_id} className="border-t bg-red-500/10">
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


/** Per-order companies: one row per active rider, an order count each.
 *  Riders left blank are not in the cycle (treated as absent, like a rider
 *  missing from a payout file); a typed 0 counts as present with no pay. */
function OrdersTable({ riders, orders, rate, company, onChange }: {
  riders: RiderOut[]; orders: Record<string, string>; rate: number; company: string
  onChange: (riderId: string, value: string) => void
}) {
  if (riders.length === 0) {
    return (
      <p className="text-sm text-slate-500 mt-4">
        No active riders at {company} yet — onboard them on the Riders page first.
      </p>
    )
  }
  return (
    <div className="mt-4 overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left border-b border-edge-soft">
          <tr>
            <th className="px-3 py-2 font-medium text-xs">Rider</th>
            <th className="px-3 py-2 font-medium text-xs">Rider id</th>
            <th className="px-3 py-2 font-medium text-xs">Hub</th>
            <th className="px-3 py-2 font-medium text-xs text-right">Orders</th>
            <th className="px-3 py-2 font-medium text-xs text-right">Payout</th>
          </tr>
        </thead>
        <tbody>
          {riders.map((r) => {
            const v = orders[r.rider_id] ?? ''
            return (
              <tr key={r.rider_id} className="border-t border-edge-soft">
                <td className="px-3 py-1.5">{r.name || <span className="text-slate-400">—</span>}</td>
                <td className="px-3 py-1.5 text-slate-600">{r.rider_id}</td>
                <td className="px-3 py-1.5 text-slate-500">{r.hub || ''}</td>
                <td className="px-3 py-1.5 text-right">
                  <input type="number" min={0} step={1} inputMode="numeric" value={v}
                         onChange={(e) => onChange(r.rider_id, e.target.value)}
                         placeholder="—"
                         className="w-24 border rounded px-2 py-1 text-sm text-right" />
                </td>
                <td className="px-3 py-1.5 text-right tabular-nums text-slate-700">
                  {v === '' ? <span className="text-slate-400">not in cycle</span> : '₹' + fmt(rate * (Number(v) || 0))}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="text-[11px] text-slate-500 mt-2">
        Leave a rider blank to keep them out of this cycle; type 0 for a rider who worked but delivered nothing.
      </p>
    </div>
  )
}


/** Salaried companies: salary per rider (saved on the rider), days present
 *  and orders per cycle, and the pay they produce — the same arithmetic the
 *  server uses, shown live so the operator sees the effect of a day off. */
function SalaryTable({ riders, attendance, salaries, company, expectedDays, incOrder, incDay, onAttendance, onSalary, onSalaryBlur }: {
  riders: RiderOut[]; attendance: Attendance; salaries: Record<string, string>; company: string
  expectedDays: number; incOrder: number; incDay: number
  onAttendance: (riderId: string, patch: Partial<{ days: string; orders: string }>) => void
  onSalary: (riderId: string, value: string) => void
  onSalaryBlur: (riderId: string, value: string) => void
}) {
  if (riders.length === 0) {
    return (
      <p className="text-sm text-slate-500 mt-4">
        No active riders at {company} yet — onboard them on the Riders page first.
      </p>
    )
  }
  const calc = (rid: string) => {
    const a = attendance[rid]
    if (!a || (a.days === '' && a.orders === '')) return null
    const salary = Number(salaries[rid]) || 0
    const present = Number(a.days) || 0
    const orders = Number(a.orders) || 0
    const off = Math.max(0, expectedDays - present)
    const base = Math.max(0, salary - off * salary / expectedDays)
    const inc = orders * incOrder + present * incDay
    return { off, base, inc, pay: base + inc, noSalary: salary <= 0 }
  }
  const inp = 'w-24 border rounded px-2 py-1 text-sm text-right'
  return (
    <div className="mt-4 overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left border-b border-edge-soft">
          <tr>
            <th className="px-3 py-2 font-medium text-xs">Rider</th>
            <th className="px-3 py-2 font-medium text-xs">Rider id</th>
            <th className="px-3 py-2 font-medium text-xs text-right">Salary / cycle (₹)</th>
            <th className="px-3 py-2 font-medium text-xs text-right">Days present</th>
            <th className="px-3 py-2 font-medium text-xs text-right">Orders</th>
            <th className="px-3 py-2 font-medium text-xs text-right">Days off</th>
            <th className="px-3 py-2 font-medium text-xs text-right">Base + incentives</th>
            <th className="px-3 py-2 font-medium text-xs text-right">Pay</th>
          </tr>
        </thead>
        <tbody>
          {riders.map((r) => {
            const a = attendance[r.rider_id] ?? { days: '', orders: '' }
            const c = calc(r.rider_id)
            return (
              <tr key={r.rider_id} className="border-t border-edge-soft">
                <td className="px-3 py-1.5">{r.name || <span className="text-slate-400">—</span>}</td>
                <td className="px-3 py-1.5 text-slate-600">{r.rider_id}</td>
                <td className="px-3 py-1.5 text-right">
                  <input type="number" min={0} step={100} value={salaries[r.rider_id] ?? ''}
                         onChange={(e) => onSalary(r.rider_id, e.target.value)}
                         onBlur={(e) => onSalaryBlur(r.rider_id, e.target.value)}
                         placeholder="set" className={inp + (!(Number(salaries[r.rider_id]) > 0) ? ' border-amber-400/60' : '')} />
                </td>
                <td className="px-3 py-1.5 text-right">
                  <input type="number" min={0} max={31} step={1} value={a.days}
                         onChange={(e) => onAttendance(r.rider_id, { days: e.target.value })}
                         placeholder="—" className={inp} />
                </td>
                <td className="px-3 py-1.5 text-right">
                  <input type="number" min={0} step={1} value={a.orders}
                         onChange={(e) => onAttendance(r.rider_id, { orders: e.target.value })}
                         placeholder="0" className={inp} />
                </td>
                <td className={'px-3 py-1.5 text-right tabular-nums' + (c && c.off > 0 ? ' text-amber-300' : ' text-slate-500')}>{c ? c.off : ''}</td>
                <td className="px-3 py-1.5 text-right tabular-nums text-slate-600">
                  {c ? `₹${fmt(c.base)} + ₹${fmt(c.inc)}` : ''}
                </td>
                <td className="px-3 py-1.5 text-right tabular-nums">
                  {!c ? <span className="text-slate-400">not in cycle</span>
                    : c.noSalary ? <span className="text-amber-300">set salary</span>
                    : '₹' + fmt(c.pay)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="text-[11px] text-slate-500 mt-2">
        Leave a rider blank to keep them out of this cycle. Salary is remembered on the rider once you tab out of the box.
        A day short of {expectedDays} costs salary ÷ {expectedDays}; incentives are ₹{incOrder} an order and ₹{incDay} a day present.
      </p>
    </div>
  )
}
