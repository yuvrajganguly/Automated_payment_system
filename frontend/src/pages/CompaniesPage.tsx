/**
 * Admin → Companies — the companies we work with and how each one pays.
 *
 * Three ways a company can pay (`payment_model`):
 *   payout_file  they send a payout file every cycle; we read it with the
 *                column names configured here, deduct EV rent, release the rest
 *   per_order    no file — the office reads each rider's order count off the
 *                company's dashboard and we pay a fixed rate per order (the
 *                counts are typed on Process Payout; rent is deducted the same
 *                way)
 *   direct       they pay riders themselves; we only keep the roster so the
 *                rider can be onboarded, hold an EV and be found by id
 *
 * Nothing is deleted here: a company that stops is deactivated so its history
 * stays readable. Company names link to their week-by-week history.
 */
import { FormEvent, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { Company } from '../api/types'
import { Spinner } from '../components/Spinner'

type Model = 'payout_file' | 'per_order' | 'direct' | 'salary'
type Cadence = 'weekly' | 'monthly' | 'slots'

const MODEL_LABEL: Record<Model, string> = {
  payout_file: 'Sends a payout file',
  per_order: 'Paid per order by us',
  direct: 'Pays riders directly',
  salary: 'Salaried, paid by us',
}
const MODEL_TONE: Record<Model, string> = {
  payout_file: 'bg-sky-500/15 text-sky-200',
  per_order: 'bg-amber-500/15 text-amber-200',
  direct: 'bg-emerald-500/15 text-emerald-200',
  salary: 'bg-fuchsia-500/15 text-fuchsia-200',
}
const CADENCE_LABEL: Record<Cadence, string> = {
  weekly: 'Weekly',
  monthly: 'Monthly',
  slots: '1-7 / 8-14 / 15-21 / 22-end',
}
const modelOf = (c: Company): Model => (c.payment_model as Model) || 'payout_file'
const cadenceOf = (c: Company): Cadence => (c.cadence as Cadence) || 'weekly'

export function CompaniesPage() {
  const [rows, setRows] = useState<Company[]>([])
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<string | null>(null)

  const reload = () => {
    setBusy(true)
    api.get<Company[]>('/companies')
      .then((cs) => { setRows(cs); setError(null) })
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false))
  }
  useEffect(reload, [])

  const active = rows.filter((c) => c.is_active)
  const inactive = rows.filter((c) => !c.is_active)

  return (
    <div className="max-w-6xl mx-auto">
      <h1 className="text-2xl font-bold mb-1">Companies</h1>
      <p className="text-slate-500 text-sm mb-6">
        Who we ride for and how each one pays. A company that <b>sends a payout file</b> is processed
        on the Process Payout page with the column names set here. One <b>paid per order by us</b> has no
        file — you type each rider's order count there and the system pays the rate per order, deducting
        rent the usual way. A <b>salaried</b> one pays each rider a fixed amount per cycle (set on the rider),
        less a day's pay for every day short of the expected days, plus incentives per order and per day
        present — you mark or upload attendance there. One that <b>pays riders directly</b> only needs the
        roster: riders can be onboarded under it and hold an EV, but there is nothing to process. Nothing is
        deleted — deactivate a company you no longer work with.
      </p>

      <AddCompanyCard companies={rows} onAdded={reload} />

      {busy && !rows.length ? <Spinner label="Loading…" /> : error ? <p className="text-red-400">{error}</p> : (
        <>
          <CompanyTable rows={active} title={`Active (${active.length})`} editing={editing}
                        setEditing={setEditing} onChanged={reload} companies={rows} />
          {inactive.length > 0 && (
            <CompanyTable rows={inactive} title={`Inactive (${inactive.length})`} editing={editing}
                          setEditing={setEditing} onChanged={reload} companies={rows} dim />
          )}
        </>
      )}
    </div>
  )
}

function CompanyTable({ rows, title, editing, setEditing, onChanged, companies, dim = false }: {
  rows: Company[]; title: string; editing: string | null; setEditing: (n: string | null) => void
  onChanged: () => void; companies: Company[]; dim?: boolean
}) {
  return (
    <section className="mb-8">
      <h2 className="font-semibold mb-2">{title}</h2>
      <div className={'panel overflow-x-auto' + (dim ? ' opacity-70' : '')}>
        <table className="w-full text-sm">
          <thead className="text-left border-b border-edge-soft">
            <tr>
              <Th>Company</Th><Th>How they pay</Th><Th>Cycle</Th><Th>Rate</Th>
              <Th>Riders</Th><Th>File columns</Th><Th>Notes</Th><Th></Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => {
              const m = modelOf(c)
              const open = editing === c.company_name
              return (
                <RowGroup key={c.company_name}>
                  <tr className="border-t border-edge-soft hover:bg-white/[0.02] align-top">
                    <td className="px-3 py-2 font-medium whitespace-nowrap">
                      <Link to={'/companies/' + encodeURIComponent(c.company_name)}
                            className="text-slate-900 hover:text-brand-300 underline decoration-dotted underline-offset-2"
                            title="Week-by-week history">
                        {c.company_name}
                      </Link>
                      {c.rider_ids_shared_with && (
                        <div className="text-[11px] text-slate-500">rider ids shared with {c.rider_ids_shared_with}</div>
                      )}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      <span className={'text-xs px-2 py-0.5 rounded ' + MODEL_TONE[m]}>{MODEL_LABEL[m]}</span>
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap text-slate-700">{CADENCE_LABEL[cadenceOf(c)]}</td>
                    <td className="px-3 py-2 whitespace-nowrap tabular-nums text-xs">
                      {m === 'per_order' ? `₹${c.per_order_rate ?? 0} / order`
                        : m === 'salary' ? (
                          <>
                            <div>{c.salary_expected_days ?? 26} days / cycle</div>
                            <div className="text-slate-500">+₹{c.incentive_per_order ?? 0}/order · +₹{c.incentive_per_day ?? 0}/day</div>
                          </>
                        ) : <span className="text-slate-400">—</span>}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap tabular-nums">
                      {c.active_riders ?? 0}<span className="text-slate-400"> / {c.rider_ids ?? 0}</span>
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-600">
                      {m === 'payout_file' ? (
                        <>
                          <div>id: <code>{c.rider_id_column}</code> · pay: <code>{c.payout_column}</code></div>
                          {c.orders_column && <div>orders: <code>{c.orders_column}</code></div>}
                          {c.hold_style && <div>COD: {c.hold_style === 'sheet' ? `sheet "${c.hold_sheet}"` : `column "${c.hold_amount_column}"`}</div>}
                        </>
                      ) : m === 'per_order' ? 'order counts typed on Process Payout'
                        : m === 'salary' ? 'attendance + orders marked or uploaded on Process Payout; salary per rider'
                        : 'nothing to process'}
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-600 max-w-[16rem]">{c.notes}</td>
                    <td className="px-3 py-2 whitespace-nowrap text-right">
                      <button type="button" onClick={() => setEditing(open ? null : c.company_name)}
                              className="text-xs px-2 py-1 rounded border border-edge hover:bg-white/[0.04]">
                        {open ? 'Close' : 'Edit'}
                      </button>
                    </td>
                  </tr>
                  {open && (
                    <tr className="border-t border-edge-soft bg-white/[0.02]">
                      <td colSpan={8} className="px-3 py-3">
                        <EditCompanyForm company={c} companies={companies}
                                         onSaved={() => { setEditing(null); onChanged() }} />
                      </td>
                    </tr>
                  )}
                </RowGroup>
              )
            })}
            {rows.length === 0 && (
              <tr><td colSpan={8} className="px-3 py-4 text-slate-500 text-sm">None.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function RowGroup({ children }: { children: React.ReactNode }) { return <>{children}</> }
function Th({ children }: { children?: React.ReactNode }) {
  return <th className="px-3 py-2 font-medium text-xs">{children}</th>
}

// ── shared form fields ───────────────────────────────────────────────────────

interface Draft {
  payment_model: Model
  cadence: Cadence
  per_order_rate: string
  salary_expected_days: string
  incentive_per_order: string
  incentive_per_day: string
  notes: string
  rider_ids_shared_with: string
  payout_sheet: string
  rider_id_column: string
  payout_column: string
  orders_column: string
  hold_style: '' | 'sheet' | 'column'
  hold_sheet: string
  hold_key_column: string
  hold_amount_column: string
  hold_status_column: string
}
const blank: Draft = {
  payment_model: 'direct', cadence: 'weekly', per_order_rate: '',
  salary_expected_days: '26', incentive_per_order: '', incentive_per_day: '', notes: '',
  rider_ids_shared_with: '', payout_sheet: '', rider_id_column: '', payout_column: '',
  orders_column: '', hold_style: '', hold_sheet: '', hold_key_column: '', hold_amount_column: '',
  hold_status_column: '',
}
const fromCompany = (c: Company): Draft => ({
  payment_model: modelOf(c), cadence: cadenceOf(c),
  per_order_rate: c.per_order_rate != null ? String(c.per_order_rate) : '',
  salary_expected_days: String(c.salary_expected_days ?? 26),
  incentive_per_order: c.incentive_per_order ? String(c.incentive_per_order) : '',
  incentive_per_day: c.incentive_per_day ? String(c.incentive_per_day) : '',
  notes: c.notes ?? '', rider_ids_shared_with: c.rider_ids_shared_with ?? '',
  payout_sheet: c.payout_sheet ?? '', rider_id_column: c.rider_id_column ?? '',
  payout_column: c.payout_column ?? '', orders_column: c.orders_column ?? '',
  hold_style: (c.hold_style as Draft['hold_style']) ?? '', hold_sheet: c.hold_sheet ?? '',
  hold_key_column: c.hold_key_column ?? '', hold_amount_column: c.hold_amount_column ?? '',
  hold_status_column: c.hold_status_column ?? '',
})
const toBody = (d: Draft) => ({
  payment_model: d.payment_model,
  cadence: d.cadence,
  per_order_rate: d.payment_model === 'per_order' && d.per_order_rate !== '' ? Number(d.per_order_rate) : null,
  salary_expected_days: d.salary_expected_days !== '' ? Number(d.salary_expected_days) : 26,
  incentive_per_order: d.incentive_per_order !== '' ? Number(d.incentive_per_order) : 0,
  incentive_per_day: d.incentive_per_day !== '' ? Number(d.incentive_per_day) : 0,
  notes: d.notes || null,
  rider_ids_shared_with: d.rider_ids_shared_with || null,
  payout_sheet: d.payout_sheet || null,
  rider_id_column: d.rider_id_column || null,
  payout_column: d.payout_column || null,
  orders_column: d.orders_column || null,
  hold_style: d.hold_style || null,
  hold_sheet: d.hold_sheet || null,
  hold_key_column: d.hold_key_column || null,
  hold_amount_column: d.hold_amount_column || null,
  hold_status_column: d.hold_status_column || null,
})

const input = 'w-full border rounded px-3 py-2 text-sm'

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-xs font-medium mb-1">{label}</span>
      {children}
      {hint && <span className="block text-[11px] text-slate-500 mt-0.5">{hint}</span>}
    </label>
  )
}

function DraftFields({ d, set, companies, self }: {
  d: Draft; set: (patch: Partial<Draft>) => void; companies: Company[]; self?: string
}) {
  const others = companies.filter((c) => c.company_name !== self)
  return (
    <>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <Field label="How do they pay?">
          <select value={d.payment_model} onChange={(e) => set({ payment_model: e.target.value as Model })} className={input}>
            <option value="direct">They pay riders directly</option>
            <option value="payout_file">They send us a payout file</option>
            <option value="per_order">We pay per order (no file)</option>
            <option value="salary">Salaried — we pay a fixed salary plus incentives</option>
          </select>
        </Field>
        <Field label="Payout cycle" hint="Sets the next cycle dates on Process Payout.">
          <select value={d.cadence} onChange={(e) => set({ cadence: e.target.value as Cadence })} className={input}>
            <option value="weekly">Weekly</option>
            <option value="monthly">Monthly</option>
            <option value="slots">Four slots a month (1-7, 8-14, 15-21, 22-end)</option>
          </select>
        </Field>
        {d.payment_model === 'per_order' ? (
          <Field label="Rate per order (₹)" hint="Payout = orders × rate; rent is deducted as usual.">
            <input type="number" min={0} step="0.5" value={d.per_order_rate}
                   onChange={(e) => set({ per_order_rate: e.target.value })} className={input} required />
          </Field>
        ) : (
          <Field label="Reuses rider ids of" hint="e.g. Nykaa pays Blitz riders under their Blitz ids.">
            <select value={d.rider_ids_shared_with} onChange={(e) => set({ rider_ids_shared_with: e.target.value })} className={input}>
              <option value="">— no —</option>
              {others.map((c) => <option key={c.company_name} value={c.company_name}>{c.company_name}</option>)}
            </select>
          </Field>
        )}
      </div>

      {d.payment_model === 'salary' && (
        <div className="mt-3">
          <div className="text-xs font-semibold text-slate-600 mb-2">
            Salary rules — each rider's salary per cycle is set on the rider (Process Payout table)
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <Field label="Expected working days per cycle" hint="Each day short costs salary ÷ this.">
              <input type="number" min={1} max={31} step={1} value={d.salary_expected_days}
                     onChange={(e) => set({ salary_expected_days: e.target.value })} className={input} required />
            </Field>
            <Field label="Incentive per order (₹)" hint="Added for every order delivered. 0 for none.">
              <input type="number" min={0} step="0.5" value={d.incentive_per_order}
                     onChange={(e) => set({ incentive_per_order: e.target.value })} className={input} placeholder="0" />
            </Field>
            <Field label="Incentive per day present (₹)" hint="Added for every day present. 0 for none.">
              <input type="number" min={0} step="1" value={d.incentive_per_day}
                     onChange={(e) => set({ incentive_per_day: e.target.value })} className={input} placeholder="0" />
            </Field>
          </div>
        </div>
      )}

      {d.payment_model === 'payout_file' && (
        <div className="mt-3">
          <div className="text-xs font-semibold text-slate-600 mb-2">Their file — column headers exactly as written in it</div>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
            <Field label="Rider id column" hint='Several spellings: separate with "|".'>
              <input value={d.rider_id_column} onChange={(e) => set({ rider_id_column: e.target.value })} className={input} required placeholder="e.g. Worker Code" />
            </Field>
            <Field label="Payout column">
              <input value={d.payout_column} onChange={(e) => set({ payout_column: e.target.value })} className={input} required placeholder="e.g. Final Payout" />
            </Field>
            <Field label="Orders column (optional)">
              <input value={d.orders_column} onChange={(e) => set({ orders_column: e.target.value })} className={input} placeholder="e.g. Total Order Completed" />
            </Field>
            <Field label="Sheet (optional)" hint='Leave blank for the first sheet; "pattern:Computation" matches by name.'>
              <input value={d.payout_sheet} onChange={(e) => set({ payout_sheet: e.target.value })} className={input} placeholder="0" />
            </Field>
          </div>
          <details className="mt-2">
            <summary className="text-xs text-slate-500 cursor-pointer">COD hold (only if their file carries COD pending)</summary>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-3 mt-2">
              <Field label="COD style">
                <select value={d.hold_style} onChange={(e) => set({ hold_style: e.target.value as Draft['hold_style'] })} className={input}>
                  <option value="">none</option>
                  <option value="column">a column in the payout sheet</option>
                  <option value="sheet">a separate sheet of line items</option>
                </select>
              </Field>
              {d.hold_style === 'column' && (
                <Field label="COD amount column">
                  <input value={d.hold_amount_column} onChange={(e) => set({ hold_amount_column: e.target.value })} className={input} placeholder="COD-Pending" />
                </Field>
              )}
              {d.hold_style === 'sheet' && (
                <>
                  <Field label="COD sheet name"><input value={d.hold_sheet} onChange={(e) => set({ hold_sheet: e.target.value })} className={input} placeholder="COD" /></Field>
                  <Field label="Rider column on it"><input value={d.hold_key_column} onChange={(e) => set({ hold_key_column: e.target.value })} className={input} placeholder="WORKER CODE" /></Field>
                  <Field label="Amount column on it"><input value={d.hold_amount_column} onChange={(e) => set({ hold_amount_column: e.target.value })} className={input} placeholder="AMOUNT" /></Field>
                </>
              )}
            </div>
          </details>
        </div>
      )}

      <div className="mt-3">
        <Field label="Notes" hint="Anything the next person should know — salary based, who to call, what is still unsettled.">
          <input value={d.notes} onChange={(e) => set({ notes: e.target.value })} className={input} />
        </Field>
      </div>
    </>
  )
}

// ── add ──────────────────────────────────────────────────────────────────────

function AddCompanyCard({ companies, onAdded }: { companies: Company[]; onAdded: () => void }) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [d, setD] = useState<Draft>(blank)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  const set = (patch: Partial<Draft>) => setD((cur) => ({ ...cur, ...patch }))

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true); setError(null); setDone(null)
    try {
      const c = await api.post<Company>('/companies', { company_name: name.trim(), ...toBody(d) })
      setDone(`${c.company_name} added — ${MODEL_LABEL[modelOf(c)].toLowerCase()}.`)
      setName(''); setD(blank); onAdded()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not add')
    } finally { setBusy(false) }
  }

  return (
    <div className="panel p-4 mb-6">
      <div className="flex items-center justify-between gap-3">
        <h2 className="font-semibold text-sm">Add a company</h2>
        <button type="button" onClick={() => setOpen((o) => !o)}
                className="text-xs px-2 py-1 rounded border border-edge hover:bg-white/[0.04]">
          {open ? 'Close' : 'New company'}
        </button>
      </div>
      {done && !open && <p className="text-xs text-emerald-300 mt-2">{done}</p>}
      {open && (
        <form onSubmit={(e) => void submit(e)} className="mt-3">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
            <Field label="Company name">
              <input value={name} onChange={(e) => setName(e.target.value)} className={input} required placeholder="e.g. Swiggy" />
            </Field>
          </div>
          <DraftFields d={d} set={set} companies={companies} />
          <div className="flex items-center gap-3 mt-4">
            <button type="submit" disabled={busy || !name.trim()}
                    className="bg-brand hover:bg-brand-700 text-white px-4 py-2 rounded text-sm font-medium disabled:opacity-50">
              {busy ? 'Adding…' : 'Add company'}
            </button>
            {error && <span className="text-sm text-red-400">{error}</span>}
          </div>
        </form>
      )}
    </div>
  )
}

// ── edit ─────────────────────────────────────────────────────────────────────

function EditCompanyForm({ company, companies, onSaved }: {
  company: Company; companies: Company[]; onSaved: () => void
}) {
  const [d, setD] = useState<Draft>(() => fromCompany(company))
  const [busy, setBusy] = useState<'save' | 'toggle' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const set = (patch: Partial<Draft>) => setD((cur) => ({ ...cur, ...patch }))
  const path = '/companies/' + encodeURIComponent(company.company_name)

  async function save(e: FormEvent) {
    e.preventDefault()
    setBusy('save'); setError(null)
    try { await api.patch<Company>(path, toBody(d)); onSaved() }
    catch (err) { setError(err instanceof Error ? err.message : 'Could not save') }
    finally { setBusy(null) }
  }
  async function toggle() {
    const next = !company.is_active
    if (!next && !window.confirm(`Deactivate ${company.company_name}? It disappears from Process Payout and onboarding; history stays.`)) return
    setBusy('toggle'); setError(null)
    try { await api.patch<Company>(path, { is_active: next }); onSaved() }
    catch (err) { setError(err instanceof Error ? err.message : 'Could not change') }
    finally { setBusy(null) }
  }

  return (
    <form onSubmit={(e) => void save(e)}>
      <DraftFields d={d} set={set} companies={companies} self={company.company_name} />
      <div className="flex flex-wrap items-center gap-3 mt-4">
        <button type="submit" disabled={!!busy}
                className="bg-brand hover:bg-brand-700 text-white px-4 py-2 rounded text-sm font-medium disabled:opacity-50">
          {busy === 'save' ? 'Saving…' : 'Save changes'}
        </button>
        <button type="button" onClick={() => void toggle()} disabled={!!busy}
                className="px-3 py-2 rounded text-sm border border-edge hover:bg-white/[0.04] disabled:opacity-50">
          {busy === 'toggle' ? '…' : company.is_active ? 'Deactivate' : 'Reactivate'}
        </button>
        {error && <span className="text-sm text-red-400">{error}</span>}
      </div>
    </form>
  )
}
