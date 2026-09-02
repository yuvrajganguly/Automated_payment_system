import { FormEvent, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { todayISO } from '../lib/dates'
import { useAuth } from '../auth/AuthContext'
import { Spinner } from '../components/Spinner'
import type { PersonOut, TransactionOut } from '../api/types'

interface RiderRow {
  rider_id: string
  company: string
  person_id: number
  name?: string | null
  hub?: string | null
  vehicle?: string | null
  account_no?: string | null
  ifsc?: string | null
  mob_no?: string | null
  is_active: boolean
}

interface CompanyOpt { company_name: string }

interface Backrent {
  applicable: boolean
  handover?: string | null
  from?: string
  to?: string
  days?: number
  amount?: number
}

const fmt = (n: number) => n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })

const EVENT_COLOR: Record<string, string> = {
  PAYOUT: 'bg-emerald-500/15', RENT: 'bg-orange-500/15', RENT_MISSED: 'bg-red-500/15',
  RENT_RECOVERED: 'bg-blue-500/15', DUES_CARRY: 'bg-yellow-500/15', ADJUSTMENT: 'bg-purple-500/15',
  DEDUCTION_SWITCH: 'bg-emerald-500/15', EV_SWAP: 'bg-indigo-500/15', OPENING: 'bg-slate-100',
}

export function PersonPage() {
  const { id } = useParams<{ id: string }>()
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin' || user?.role === 'creator'
  const isCreator = user?.role === 'creator'
  const [person, setPerson] = useState<PersonOut | null>(null)
  const [txns, setTxns] = useState<TransactionOut[]>([])
  const [companies, setCompanies] = useState<CompanyOpt[]>([])
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [splitOpen, setSplitOpen] = useState(false)
  const [backrent, setBackrent] = useState<Backrent | null>(null)
  const [brBusy, setBrBusy] = useState(false)
  const [brMsg, setBrMsg] = useState<string | null>(null)

  const load = () => {
    if (!id) return
    setBusy(true); setError(null)
    Promise.all([
      api.get<PersonOut>('/persons/' + id),
      api.get<TransactionOut[]>('/ledger/' + id),
    ]).then(([p, t]) => {
      setPerson(p); setTxns(t)
      if (p.ev?.ev_id) {
        api.get<Backrent>('/evs/' + encodeURIComponent(p.ev.ev_id) + '/backrent')
          .then(setBackrent).catch(() => setBackrent(null))
      } else setBackrent(null)
    })
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false))
  }

  async function addBackrent() {
    if (!person?.ev?.ev_id) return
    setBrBusy(true); setBrMsg(null)
    try {
      await api.post('/evs/backrent', { ev_id: person.ev.ev_id })
      setBrMsg('Added to arrears'); load()
    } catch (e) { setBrMsg(e instanceof Error ? e.message : 'Failed') }
    finally { setBrBusy(false) }
  }
  useEffect(load, [id])
  useEffect(() => { api.get<CompanyOpt[]>('/companies').then(setCompanies).catch(() => {}) }, [])

  if (busy && !person) return <Spinner label="Loading…" />
  if (error || !person) return <p className="text-red-400">{error ?? 'Not found'}</p>

  return (
    <div className="max-w-6xl mx-auto">
      <Link to="/riders" className="text-sm text-brand underline">← Back to riders</Link>
      <h1 className="text-2xl font-bold mt-2 mb-1">
        {person.display_name} <span className="text-slate-400 text-base">#{person.person_id}</span>
      </h1>
      <p className="text-slate-500 text-sm mb-6">
        Deduction anchor: {person.deduction_company ?? '-'} / {person.deduction_rider_id ?? '-'}
      </p>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
        <Stat label="Current Balance" value={fmt(person.current_balance)} bad={person.current_balance < 0} />
        <Stat label="Arrears Outstanding" value={fmt(person.arrears_outstanding)} bad={person.arrears_outstanding > 0} />
        <Stat label="Total Dues" value={fmt(person.arrears_outstanding - person.current_balance)} bad={(person.arrears_outstanding - person.current_balance) > 0} />
        <Stat label="Rider IDs" value={person.riders.length.toString()} />
        <Stat label="Open EV"
              value={person.ev?.ev_id ?? '-'}
              linkTo={person.ev ? '/evs/' + encodeURIComponent(person.ev.ev_id) : undefined} />
      </div>

      {person.ev && (
        <div className="panel p-4 mb-6">
          <h3 className="font-semibold mb-2">EV Assignment</h3>
          <dl className="grid grid-cols-2 md:grid-cols-4 text-sm gap-y-1">
            <dt className="text-slate-500">EV ID</dt>
            <dd>
              <Link to={'/evs/' + encodeURIComponent(person.ev.ev_id)}
                    className="text-brand underline">
                {person.ev.ev_id}
              </Link>
            </dd>
            <dt className="text-slate-500">Provider / Model</dt><dd>{person.ev.provider} {person.ev.model}</dd>
            <dt className="text-slate-500">Weekly rate</dt><dd>{fmt(person.ev.weekly_rate)}</dd>
            <dt className="text-slate-500">Handover</dt><dd>{person.ev.handover_date ?? '-'}</dd>
            <dt className="text-slate-500">Rent through</dt><dd>{person.ev.rent_charged_through ?? '-'}</dd>
          </dl>
        </div>
      )}

      {isAdmin && backrent?.applicable && (
        <div className="mb-6 rounded border border-amber-300 bg-amber-500/10 p-3 text-sm">
          <div className="font-medium text-amber-200">Backdated handover — un-billed rent</div>
          <p className="text-amber-200 text-xs mt-1">
            EV handed over {backrent.handover}. {backrent.days} un-billed day(s)
            ({backrent.from} → {backrent.to}) — about ₹{fmt(backrent.amount ?? 0)} was
            never charged. Add it to this rider's EV arrears?
          </p>
          <button type="button" onClick={addBackrent} disabled={brBusy}
                  className="mt-2 bg-amber-600 hover:bg-amber-700 text-white px-3 py-1.5 rounded text-xs disabled:opacity-50">
            {brBusy ? '…' : `Add ₹${fmt(backrent.amount ?? 0)} to arrears`}
          </button>
          {brMsg && <span className="ml-2 text-xs">{brMsg}</span>}
        </div>
      )}

      {person.ev_history && person.ev_history.length > 0 && (
        <Section title={`EV History (${person.ev_history.length})`}>
          <table className="w-full text-sm">
            <thead className="bg-slate-100 text-left">
              <tr>
                <Th>EV ID</Th><Th>Provider</Th><Th>Model</Th>
                <Th right>Weekly</Th><Th>Handover</Th><Th>Returned</Th>
                <Th>Rent through</Th>
              </tr>
            </thead>
            <tbody>
              {person.ev_history.map((h) => (
                <tr key={h.assignment_id} className={'border-t ' +
                    (h.returned_date === null ? 'bg-amber-500/10' : '')}>
                  <Td>
                    <Link to={'/evs/' + encodeURIComponent(h.ev_id)}
                          className="text-brand underline">{h.ev_id}</Link>
                  </Td>
                  <Td>{h.provider}</Td>
                  <Td>{h.model}</Td>
                  <Td right>{fmt(h.weekly_rate)}</Td>
                  <Td>{h.handover_date ?? '-'}</Td>
                  <Td>
                    {h.returned_date === null
                      ? <span className="text-amber-300 font-medium">open</span>
                      : h.returned_date}
                  </Td>
                  <Td>{h.rent_charged_through ?? '-'}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}

      {isAdmin && person.riders.length >= 2 && (
        <div className="mb-3 flex justify-end">
          <button onClick={() => setSplitOpen(true)}
                  className="text-xs px-3 py-1.5 rounded bg-slate-200 hover:bg-slate-300">
            Split person…
          </button>
        </div>
      )}

      <Section title={'Rider IDs (' + person.riders.length + ')'}>
        <table className="w-full text-sm">
          <thead className="bg-slate-100 text-left">
            <tr>
              <Th>Rider ID</Th><Th>Company</Th><Th>Name</Th><Th>Hub</Th>
              <Th>Vehicle</Th><Th>Account</Th><Th>IFSC</Th><Th>Phone</Th><Th>Active</Th>
              {isAdmin && <Th>{''}</Th>}
            </tr>
          </thead>
          <tbody>
            {person.riders.map((r) => (
              <RiderRow key={r.rider_id + ':' + r.company} rider={r as RiderRow}
                        companies={companies}
                        isAdmin={isAdmin} onSaved={load} />
            ))}
          </tbody>
        </table>
      </Section>

      {isAdmin && (
        <AddAtAnotherCompanyCard personId={person.person_id}
                                 displayName={person.display_name}
                                 existingCompanies={person.riders.map((r) => r.company)}
                                 companies={companies}
                                 onAdded={load} />
      )}

      <Section title={'Transactions (' + txns.length + ')'}>
        <table className="w-full text-sm">
          <thead className="bg-slate-100 text-left">
            <tr><Th>ID</Th><Th>Cycle</Th><Th>Event</Th><Th>Rider / Co</Th><Th right>Amount</Th><Th right>Bal After</Th><Th>Days</Th><Th>Remarks</Th>{isCreator && <Th>{''}</Th>}</tr>
          </thead>
          <tbody>
            {txns.map((t) => (
              <TxnRow key={t.id} t={t} isCreator={isCreator} onChanged={load} />
            ))}
          </tbody>
        </table>
        {txns.length === 0 && <p className="p-3 text-slate-500 text-sm">No transactions yet.</p>}
      </Section>

      {isCreator && (
        <DangerZone
          kind="person"
          label={person.display_name}
          deletePath={`/api/creator/persons/${person.person_id}?cascade=true`}
          onDeleted={() => { window.location.href = '/riders' }}
        />
      )}

      {isAdmin && <RentPaymentForm personId={person.person_id} onPosted={load} />}
      {isAdmin && <AdjustmentForm personId={person.person_id} onPosted={load} />}

      {splitOpen && person && (
        <SplitPersonModal
          person={person}
          onClose={() => setSplitOpen(false)}
          onSplit={(newId) => { setSplitOpen(false); window.location.href = '/persons/' + newId }}
        />
      )}
    </div>
  )
}

function RentPaymentForm({ personId, onPosted }: { personId: number; onPosted: () => void }) {
  const today = todayISO()   // local date; the UTC version was yesterday before 05:30 IST
  const [amount, setAmount] = useState('')
  const [paidOn, setPaidOn] = useState(today)
  const [periodStart, setPeriodStart] = useState('')
  const [periodEnd, setPeriodEnd] = useState('')
  const [remarks, setRemarks] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [tone, setTone] = useState<'ok' | 'err'>('ok')

  // Both period dates are optional, but must come together if either is set.
  const periodValid =
    (!periodStart && !periodEnd) ||
    (!!periodStart && !!periodEnd && periodStart <= periodEnd)

  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setMsg(null)
    try {
      const amt = parseFloat(amount)
      if (!amt || amt <= 0 || isNaN(amt)) throw new Error('Amount must be positive.')
      if (!periodValid) throw new Error('Coverage period must have both dates with end ≥ start.')
      const body: Record<string, unknown> = {
        person_id: personId, amount: amt, paid_on: paidOn, remarks,
      }
      if (periodStart && periodEnd) {
        body.period_start = periodStart
        body.period_end = periodEnd
      }
      const r = await api.post<{
        applied_to_arrears: number; applied_to_rent: number; new_balance: number
        rent_charged_through_advanced_to: string | null
      }>('/ledger/rent-payment', body)
      setTone('ok')
      setMsg(
        `Recorded. ${r.applied_to_arrears > 0 ? `Arrears: ${fmt(r.applied_to_arrears)} · ` : ''}` +
        `Rent: ${fmt(r.applied_to_rent)} · New balance: ${fmt(r.new_balance)}` +
        (r.rent_charged_through_advanced_to
          ? ` · Rent meter → ${r.rent_charged_through_advanced_to}`
          : ''),
      )
      setAmount(''); setRemarks(''); setPeriodStart(''); setPeriodEnd(''); onPosted()
    } catch (err) {
      setTone('err'); setMsg(err instanceof Error ? err.message : 'Failed')
    } finally { setBusy(false) }
  }

  return (
    <div className="panel p-4 mt-6 border-l-[3px] border-l-emerald-400">
      <h3 className="font-semibold mb-1">Log Manual Rent Payment</h3>
      <p className="text-xs text-slate-500 mb-3">
        Use when a rider pays rent in cash / UPI outside the bank reconciliation.
        Goes against outstanding EV arrears first, then current-cycle rent —
        so it shows up correctly in the EV Rent Details tab.
        Fill in the optional <b>coverage period</b> to mark which days the
        payment covers; the EV's rent meter will advance to the end date so the
        engine doesn't re-charge for those days.
      </p>
      <form onSubmit={submit} className="flex flex-wrap gap-2 items-end">
        <label className="block text-sm">
          <span className="block text-xs">Amount paid *</span>
          <input value={amount} onChange={(e) => setAmount(e.target.value)}
                 type="number" step="0.01" min="0"
                 className="border rounded px-3 py-1.5 w-32" />
        </label>
        <label className="block text-sm">
          <span className="block text-xs">Paid on</span>
          <input value={paidOn} onChange={(e) => setPaidOn(e.target.value)}
                 type="date" className="border rounded px-3 py-1.5" />
        </label>
        <label className="block text-sm">
          <span className="block text-xs">Covers from</span>
          <input value={periodStart} onChange={(e) => setPeriodStart(e.target.value)}
                 type="date" className="border rounded px-3 py-1.5" />
        </label>
        <label className="block text-sm">
          <span className="block text-xs">Covers to</span>
          <input value={periodEnd} onChange={(e) => setPeriodEnd(e.target.value)}
                 type="date" className="border rounded px-3 py-1.5" />
        </label>
        <label className="block text-sm flex-1 min-w-[200px]">
          <span className="block text-xs">Remarks (optional)</span>
          <input value={remarks} onChange={(e) => setRemarks(e.target.value)}
                 placeholder="e.g. UPI to owner, ref# 12345"
                 className="w-full border rounded px-3 py-1.5" />
        </label>
        <button type="submit" disabled={busy || !amount || !periodValid}
                className="bg-emerald-600 hover:bg-emerald-500 text-white px-3 py-1.5 rounded disabled:opacity-50">
          {busy ? 'Posting…' : 'Record rent payment'}
        </button>
        {msg && (
          <span className={'text-xs ' + (tone === 'err' ? 'text-red-400' : 'text-emerald-300')}>
            {msg}
          </span>
        )}
      </form>
    </div>
  )
}

function AdjustmentForm({ personId, onPosted }: { personId: number; onPosted: () => void }) {
  const [amount, setAmount] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)

  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setMsg(null)
    try {
      const amt = parseFloat(amount)
      if (!amt || isNaN(amt)) throw new Error('Amount must be a non-zero number')
      const r = await api.post<{ new_balance: number }>('/ledger/adjustments',
                                                       { person_id: personId, amount: amt, reason })
      setMsg('Posted. New balance: ' + fmt(r.new_balance))
      setAmount(''); setReason(''); onPosted()
    } catch (err) { setMsg(err instanceof Error ? err.message : 'Failed') }
    finally { setBusy(false) }
  }
  return (
    <div className="panel p-4 mt-6">
      <h3 className="font-semibold mb-2">Post Manual Adjustment</h3>
      <p className="text-xs text-slate-500 mb-3">Positive = credit (reduces dues). Negative = debit (adds dues / penalty).</p>
      <form onSubmit={submit} className="flex flex-wrap gap-2 items-end">
        <label className="block text-sm">
          <span className="block text-xs">Amount</span>
          <input value={amount} onChange={(e) => setAmount(e.target.value)} type="number" step="0.01" className="border rounded px-3 py-1.5 w-36" />
        </label>
        <label className="block text-sm flex-1 min-w-[200px]">
          <span className="block text-xs">Reason *</span>
          <input value={reason} onChange={(e) => setReason(e.target.value)} className="w-full border rounded px-3 py-1.5" />
        </label>
        <button type="submit" disabled={busy || !reason || !amount}
                className="bg-brand hover:bg-brand-700 text-white px-3 py-1.5 rounded disabled:opacity-50">
          {busy ? 'Posting…' : 'Post'}
        </button>
        {msg && <span className="text-xs">{msg}</span>}
      </form>
    </div>
  )
}

function Stat({ label, value, bad, linkTo }:
  { label: string; value: string; bad?: boolean; linkTo?: string }) {
  const inner = (
    <p className={'text-lg font-semibold ' + (bad ? 'text-red-400' : '')
                   + (linkTo ? ' text-brand underline hover:opacity-80' : '')}>
      {value}
    </p>
  )
  return <div className="panel p-3">
    <p className="text-xs text-slate-500">{label}</p>
    {linkTo ? <Link to={linkTo}>{inner}</Link> : inner}
  </div>
}
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <div className="mb-6">
    <h3 className="font-semibold mb-2">{title}</h3>
    <div className="panel overflow-x-auto">{children}</div>
  </div>
}
function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return <th className={'px-3 py-2 font-medium text-xs ' + (right ? 'text-right' : '')}>{children}</th>
}
function Td({ children, right, className = '' }: { children: React.ReactNode; right?: boolean; className?: string }) {
  return <td className={'px-3 py-2 ' + (right ? 'text-right ' : '') + className}>{children}</td>
}

function RiderRow({
  rider, companies, isAdmin, onSaved,
}: {
  rider: RiderRow; companies: CompanyOpt[]; isAdmin: boolean; onSaved: () => void
}) {
  const [editing, setEditing] = useState(false)
  const initial = () => ({
    new_rider_id: rider.rider_id,
    new_company: rider.company,
    name: rider.name ?? '',
    hub: rider.hub ?? '',
    vehicle: rider.vehicle ?? '',
    account_no: rider.account_no ?? '', mob_no: rider.mob_no ?? '',
    ifsc: rider.ifsc ?? '',
  })
  const [form, setForm] = useState(initial)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  function reset() { setForm(initial()); setErr(null); setEditing(false) }

  async function save() {
    setBusy(true); setErr(null)
    try {
      // Edge case: the existing row has no rider_id (placeholder situation).
      // PATCH /riders/{rider_id} won't match an empty path segment, so use
      // /riders/rename-rider-id to set the rider_id first, then PATCH the rest.
      let currentRid = rider.rider_id
      if (!currentRid && form.new_rider_id) {
        await api.post('/riders/rename-rider-id', {
          person_id: rider.person_id,
          company: rider.company,
          new_rider_id: form.new_rider_id,
          current_rider_id: '',
        })
        currentRid = form.new_rider_id
      }
      if (!currentRid) {
        throw new Error('Type a Rider ID before saving (or leave blank to auto-assign elsewhere).')
      }
      const url = '/riders/' + encodeURIComponent(currentRid) +
                  '?company=' + encodeURIComponent(rider.company)
      const body: Record<string, string | undefined> = {
        name: form.name, hub: form.hub, vehicle: form.vehicle,
        account_no: form.account_no, ifsc: form.ifsc, mob_no: form.mob_no,
      }
      if (form.new_rider_id && form.new_rider_id !== currentRid)
        body.new_rider_id = form.new_rider_id
      if (form.new_company && form.new_company !== rider.company)
        body.new_company = form.new_company
      await api.patch(url, body)
      setEditing(false); onSaved()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed')
    } finally {
      setBusy(false)
    }
  }

  if (!editing) {
    return (
      <tr className="border-t">
        <Td>{rider.rider_id}</Td>
        <Td>{rider.company}</Td>
        <Td>{rider.name}</Td>
        <Td>{rider.hub ?? '-'}</Td>
        <Td>{rider.vehicle ?? '-'}</Td>
        <Td>{rider.account_no ?? '-'}</Td>
        <Td>{rider.ifsc ?? '-'}</Td>
        <Td>{rider.mob_no ?? '-'}</Td>
        <Td>{rider.is_active ? 'yes' : 'no'}</Td>
        {isAdmin && (
          <Td>
            <button onClick={() => setEditing(true)}
                    className="text-xs text-brand underline hover:opacity-80">
              Edit
            </button>
          </Td>
        )}
      </tr>
    )
  }
  return (
    <tr className="border-t bg-amber-500/10">
      <Td><Cell v={form.new_rider_id}
                on={(v) => setForm({ ...form, new_rider_id: v })} /></Td>
      <Td>
        <select value={form.new_company}
                onChange={(e) => setForm({ ...form, new_company: e.target.value })}
                className="border rounded px-1 py-0.5 text-xs">
          {companies.map((c) =>
            <option key={c.company_name} value={c.company_name}>{c.company_name}</option>)}
        </select>
      </Td>
      <Td><Cell v={form.name} on={(v) => setForm({ ...form, name: v })} /></Td>
      <Td><Cell v={form.hub} on={(v) => setForm({ ...form, hub: v })} /></Td>
      <Td>
        <select value={form.vehicle}
                onChange={(e) => setForm({ ...form, vehicle: e.target.value })}
                className="border rounded px-1 py-0.5 text-xs">
          {['', 'EV', 'BIKE', 'OTHER'].map((o) =>
            <option key={o} value={o}>{o || '-'}</option>)}
        </select>
      </Td>
      <Td><Cell v={form.account_no} on={(v) => setForm({ ...form, account_no: v })} /></Td>
      <Td><Cell v={form.ifsc}
                on={(v) => setForm({ ...form, ifsc: v.toUpperCase() })}
                placeholder="auto-CAPS" /></Td>
      <Td><Cell v={form.mob_no} on={(v) => setForm({ ...form, mob_no: v })} /></Td>
      <Td>{rider.is_active ? 'yes' : 'no'}</Td>
      <Td>
        <div className="flex flex-col gap-1">
          <button onClick={save} disabled={busy}
                  className="text-xs bg-brand text-white px-2 py-0.5 rounded disabled:opacity-50">
            {busy ? '…' : 'Save'}
          </button>
          <button onClick={reset} disabled={busy}
                  className="text-xs text-slate-600 underline">Cancel</button>
          {err && <span className="text-xs text-red-400">{err}</span>}
        </div>
      </Td>
    </tr>
  )
}

function AddAtAnotherCompanyCard({
  personId, displayName, existingCompanies, companies, onAdded,
}: {
  personId: number; displayName: string; existingCompanies: string[];
  companies: CompanyOpt[]; onAdded: () => void
}) {
  const [open, setOpen] = useState(false)
  // Show every active company — a rider can legitimately have a second
  // rider_id at a company they're already on (split worker codes, replaced ID,
  // etc.). The (rider_id, company) PK on rider_master still prevents duplicates.
  const allCompanies = companies.map((c) => c.company_name)
  const usedSet = new Set(existingCompanies)
  const empty = {
    company: '', rider_id: '',
    hub: '', vehicle: '', account_no: '', ifsc: '',
  }
  const [form, setForm] = useState(empty)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [tone, setTone] = useState<'ok' | 'err'>('ok')

  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setMsg(null)
    try {
      const r = await api.post<{ rider_id: string }>('/riders', {
        ...form,
        name: displayName,
        person_id: personId,
      })
      setTone('ok'); setMsg(`Added at ${form.company} (rider_id=${r.rider_id})`)
      setForm({ ...empty, company: '' })
      onAdded()
    } catch (err) {
      setTone('err'); setMsg(err instanceof Error ? err.message : 'Failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="panel p-4 mb-6">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold">Add to another company</h3>
        <button onClick={() => setOpen(!open)}
                className="text-sm text-brand underline">{open ? 'Close' : 'Open'}</button>
      </div>
      {open && (
        <form onSubmit={submit} className="grid grid-cols-2 gap-2 mt-3 text-sm">
          <label className="block">
            <span className="block text-xs text-slate-600">Company *</span>
            <select value={form.company}
                    onChange={(e) => setForm({ ...form, company: e.target.value })}
                    className="w-full border rounded px-2 py-1">
              <option value="">(pick one)</option>
              {allCompanies.map((c) => (
                <option key={c} value={c}>
                  {c}{usedSet.has(c) ? ' — already added (new rider_id will create a second row)' : ''}
                </option>
              ))}
            </select>
          </label>
          <Field label="Rider ID (optional)" v={form.rider_id}
                 on={(v) => setForm({ ...form, rider_id: v })} />
          <Field label="Hub" v={form.hub} on={(v) => setForm({ ...form, hub: v })} />
          <FieldSelect label="Vehicle" v={form.vehicle}
                       on={(v) => setForm({ ...form, vehicle: v })}
                       options={['', 'EV', 'BIKE', 'OTHER']} />
          <Field label="Account #" v={form.account_no}
                 on={(v) => setForm({ ...form, account_no: v })} />
          <Field label="IFSC" v={form.ifsc}
                 on={(v) => setForm({ ...form, ifsc: v.toUpperCase() })} />
          <div className="col-span-2 flex gap-2 items-center mt-1">
            <button type="submit" disabled={busy || !form.company}
                    className="bg-brand hover:bg-brand-700 text-white px-3 py-1.5 rounded disabled:opacity-50">
              {busy ? '…' : 'Add'}
            </button>
            {msg && <span className={'text-xs ' + (tone === 'err' ? 'text-red-400' : 'text-emerald-300')}>{msg}</span>}
          </div>
          {form.company && usedSet.has(form.company) && (
            <p className="col-span-2 text-xs text-amber-300">
              This person already has a rider_id at {form.company}. Type a
              different rider_id below to add a second one — leaving it blank
              will fail because the placeholder collides with the existing row.
            </p>
          )}
        </form>
      )}
    </div>
  )
}

function Field({ label, v, on }: { label: string; v: string; on: (v: string) => void }) {
  return <label className="block">
    <span className="block text-xs text-slate-600">{label}</span>
    <input value={v} onChange={(e) => on(e.target.value)}
           className="w-full border rounded px-2 py-1" />
  </label>
}
function FieldSelect({ label, v, on, options }:
  { label: string; v: string; on: (v: string) => void; options: string[] }) {
  return <label className="block">
    <span className="block text-xs text-slate-600">{label}</span>
    <select value={v} onChange={(e) => on(e.target.value)}
            className="w-full border rounded px-2 py-1">
      {options.map((o) => <option key={o} value={o}>{o || '(none)'}</option>)}
    </select>
  </label>
}

function SplitPersonModal({ person, onClose, onSplit }:
  { person: PersonOut; onClose: () => void; onSplit: (newPersonId: number) => void }) {
  const [moveSet, setMoveSet] = useState<Set<string>>(new Set())
  const [newName, setNewName] = useState(person.display_name + ' (split)')
  const [moveOpenEv, setMoveOpenEv] = useState(false)
  const [balFrac, setBalFrac] = useState(0)
  const [arrFrac, setArrFrac] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const keyOf = (r: { rider_id: string; company: string }) => r.rider_id + '|' + r.company
  const stayCount = person.riders.length - moveSet.size
  const canSubmit = moveSet.size > 0 && stayCount > 0 && newName.trim().length > 0

  async function submit() {
    setBusy(true); setError(null)
    try {
      const rider_ids = person.riders
        .filter((r) => moveSet.has(keyOf(r)))
        .map((r) => ({ rider_id: r.rider_id, company: r.company }))
      const r = await api.post<{ new_person_id: number }>(
        '/persons/' + person.person_id + '/split',
        {
          rider_ids,
          new_display_name: newName.trim(),
          transfer_open_ev: moveOpenEv,
          transfer_balance_fraction: balFrac,
          transfer_arrears_fraction: arrFrac,
        },
      )
      onSplit(r.new_person_id)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-[2px] flex items-center justify-center p-4 z-50">
      <div className="panel-pop w-full max-w-2xl max-h-[90vh] flex flex-col">
        <div className="px-5 py-3 border-b flex items-center justify-between">
          <div>
            <h3 className="font-semibold">Split {person.display_name} into two people</h3>
            <p className="text-xs text-slate-500">
              Pick the rider IDs that should move to a new person. Their
              transactions and COD holds follow automatically.
            </p>
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-700">✕</button>
        </div>
        <div className="px-5 py-3 overflow-y-auto space-y-3">
          <table className="w-full text-xs">
            <thead className="bg-slate-50 text-left">
              <tr>
                <th className="px-2 py-1">Move?</th>
                <th className="px-2 py-1">Rider ID</th>
                <th className="px-2 py-1">Company</th>
                <th className="px-2 py-1">Name</th>
                <th className="px-2 py-1">Hub</th>
                <th className="px-2 py-1">Account</th>
              </tr>
            </thead>
            <tbody>
              {person.riders.map((r) => {
                const k = keyOf(r)
                return (
                  <tr key={k} className={'border-t ' + (moveSet.has(k) ? 'bg-amber-500/10' : '')}>
                    <td className="px-2 py-1">
                      <input type="checkbox" checked={moveSet.has(k)}
                             onChange={(e) => {
                               const s = new Set(moveSet)
                               if (e.target.checked) s.add(k); else s.delete(k)
                               setMoveSet(s)
                             }} />
                    </td>
                    <td className="px-2 py-1">{r.rider_id}</td>
                    <td className="px-2 py-1">{r.company}</td>
                    <td className="px-2 py-1">{r.name}</td>
                    <td className="px-2 py-1">{r.hub ?? '-'}</td>
                    <td className="px-2 py-1">{r.account_no ?? '-'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <p className="text-xs text-slate-500">
            Moving {moveSet.size}; keeping {stayCount} on {person.display_name}.
          </p>

          <div className="border-t pt-3 space-y-2">
            <label className="block text-sm">
              <span className="block text-xs text-slate-600">New person's display name</span>
              <input value={newName} onChange={(e) => setNewName(e.target.value)}
                     className="w-full border rounded px-2 py-1" />
            </label>
            {person.ev && (
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={moveOpenEv}
                       onChange={(e) => setMoveOpenEv(e.target.checked)} />
                Move the open EV ({person.ev.ev_id}) to the new person
              </label>
            )}
            <div className="grid grid-cols-2 gap-2 text-sm">
              <label className="block">
                <span className="block text-xs text-slate-600">Transfer balance (fraction 0–1)</span>
                <input type="number" step="0.05" min="0" max="1"
                       value={balFrac}
                       onChange={(e) => setBalFrac(parseFloat(e.target.value) || 0)}
                       className="w-full border rounded px-2 py-1" />
              </label>
              <label className="block">
                <span className="block text-xs text-slate-600">Transfer arrears (fraction 0–1)</span>
                <input type="number" step="0.05" min="0" max="1"
                       value={arrFrac}
                       onChange={(e) => setArrFrac(parseFloat(e.target.value) || 0)}
                       className="w-full border rounded px-2 py-1" />
              </label>
            </div>
            <p className="text-xs text-slate-500">
              0 = the source keeps everything. 1 = it all moves to the new person.
              Useful when the two halves were never the same human and the
              ledger needs to follow one of them.
            </p>
          </div>

          {error && <p className="text-red-400 text-xs">{error}</p>}
        </div>
        <div className="px-5 py-3 border-t flex justify-end gap-2">
          <button onClick={onClose} disabled={busy}
                  className="text-sm px-3 py-1.5 rounded bg-slate-200 hover:bg-slate-300">Cancel</button>
          <button onClick={submit} disabled={!canSubmit || busy}
                  className="text-sm px-3 py-1.5 rounded bg-brand text-white hover:bg-brand-700 disabled:opacity-50">
            {busy ? 'Splitting…' : 'Create new person'}
          </button>
        </div>
      </div>
    </div>
  )
}

function Cell({ v, on, placeholder }: { v: string; on: (v: string) => void; placeholder?: string }) {
  return <input value={v} onChange={(e) => on(e.target.value)} placeholder={placeholder}
                className="border rounded px-1 py-0.5 text-xs w-full" />
}

function TxnRow({ t, isCreator, onChanged }:
  { t: TransactionOut; isCreator: boolean; onChanged: () => void }) {
  const [editing, setEditing] = useState(false)
  const [amount, setAmount] = useState(t.amount.toString())
  const [remarks, setRemarks] = useState(t.remarks ?? '')
  const [busy, setBusy] = useState(false)

  const [err, setErr] = useState<string | null>(null)

  async function save() {
    const amt = parseFloat(amount)
    if (!Number.isFinite(amt)) { setErr('Amount must be a number.'); return }
    setBusy(true); setErr(null)
    try {
      await api.patch('/creator/transactions/' + t.id, { amount: amt, remarks })
      setEditing(false); onChanged()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed')   // was: try/finally with no catch
    } finally { setBusy(false) }
  }
  async function voidIt() {
    if (!confirm('Void transaction #' + t.id + '? Balance will be recomputed.')) return
    setBusy(true); setErr(null)
    try {
      await api.delete('/creator/transactions/' + t.id)
      onChanged()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed')
    } finally { setBusy(false) }
  }

  if (editing) {
    return (
      <tr className="border-t bg-amber-500/10">
        <Td>{t.id}</Td>
        <Td className="text-xs">{t.cycle_start} → {t.cycle_end}</Td>
        <Td><span className={'text-xs px-1.5 py-0.5 rounded ' + (EVENT_COLOR[t.event_type] ?? 'bg-slate-100')}>{t.event_type}</span></Td>
        <Td className="text-xs">{(t.rider_id || '-') + ' / ' + (t.company || '-')}</Td>
        <Td right>
          <input type="number" step="0.01" value={amount}
                 onChange={(e) => setAmount(e.target.value)}
                 className="border rounded px-1 py-0.5 text-xs w-24 text-right" />
        </Td>
        <Td right>{fmt(t.balance_after)}</Td>
        <Td>{t.days ?? '-'}</Td>
        <Td>
          <input value={remarks} onChange={(e) => setRemarks(e.target.value)}
                 className="border rounded px-1 py-0.5 text-xs w-full" />
        </Td>
        <Td>
          <div className="flex flex-col gap-1">
            <button onClick={save} disabled={busy}
                    className="text-xs bg-purple-600 text-white px-2 py-0.5 rounded">
              Save
            </button>
            <button onClick={() => setEditing(false)} disabled={busy}
                    className="text-xs text-slate-600 underline">Cancel</button>
            {err && <span role="alert" className="text-[11px] text-rose-400">{err}</span>}
          </div>
        </Td>
      </tr>
    )
  }
  if (err) {
    // Void failed on the non-editing row: surface it inline instead of an alert().
    return (
      <tr className="border-t">
        <td colSpan={9} className="px-3 py-2 text-xs text-rose-400" role="alert">
          #{t.id}: {err} <button className="underline ml-2" onClick={() => setErr(null)}>dismiss</button>
        </td>
      </tr>
    )
  }
  return (
    <tr className="border-t">
      <Td>{t.id}</Td>
      <Td className="text-xs">{t.cycle_start} → {t.cycle_end}</Td>
      <Td><span className={'text-xs px-1.5 py-0.5 rounded ' + (EVENT_COLOR[t.event_type] ?? 'bg-slate-100')}>{t.event_type}</span></Td>
      <Td className="text-xs">{(t.rider_id || '-') + ' / ' + (t.company || '-')}</Td>
      <Td right>{fmt(t.amount)}</Td>
      <Td right>{fmt(t.balance_after)}</Td>
      <Td>{t.days ?? '-'}</Td>
      <Td className="text-xs">{t.remarks ?? ''}</Td>
      {isCreator && (
        <Td>
          <div className="flex gap-2">
            <button onClick={() => setEditing(true)}
                    className="text-xs text-purple-300 underline">edit</button>
            <button onClick={voidIt}
                    className="text-xs text-red-400 underline">void</button>
          </div>
        </Td>
      )}
    </tr>
  )
}

export function DangerZone({ kind, label, deletePath, onDeleted }:
  { kind: string; label: string; deletePath: string; onDeleted: () => void }) {
  const [confirmText, setConfirmText] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function go() {
    if (confirmText !== 'DELETE') return
    if (!confirm(`Hard delete this ${kind} (${label})? Irreversible.`)) return
    setBusy(true); setErr(null)
    try {
      // deletePath is given as a full "/api/..." path by callers.
      await api.delete(deletePath.replace(/^\/api/, ''))
      onDeleted()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed')
    } finally { setBusy(false) }
  }
  return (
    <div className="mt-8 bg-red-500/10 border border-red-400/30 rounded-lg p-4">
      <h3 className="font-semibold text-red-300 text-sm mb-2">Danger Zone — Creator only</h3>
      <p className="text-xs text-red-300 mb-3">
        Hard-delete this {kind}. Cascades through every ledger row and balance.
        Type <code className="bg-panel px-1 rounded">DELETE</code> below to confirm.
      </p>
      <div className="flex flex-wrap gap-2 items-center">
        <input value={confirmText} onChange={(e) => setConfirmText(e.target.value)}
               placeholder="type DELETE to enable"
               className="border rounded px-2 py-1 text-sm" />
        <button onClick={go} disabled={busy || confirmText !== 'DELETE'}
                className="bg-red-600 hover:bg-red-500 text-white text-sm px-3 py-1.5 rounded disabled:opacity-50">
          {busy ? '…' : `Hard delete ${kind}`}
        </button>
        {err && <span className="text-xs text-red-300">{err}</span>}
      </div>
    </div>
  )
}
