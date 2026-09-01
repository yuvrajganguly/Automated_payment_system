import { FormEvent, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Spinner } from '../components/Spinner'
import { DangerZone } from './PersonPage'

const fmt = (n: number) =>
  n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })

interface Assignment {
  assignment_id: number
  person_id: number
  display_name: string | null
  handover_date: string | null
  returned_date: string | null
  rent_charged_through: string | null
}
interface MaintRow {
  id: number
  from_date: string
  to_date: string | null
  reason: string | null
  created_by: string | null
  created_at: string | null
}
interface Profile {
  unit: { ev_id: string; status: string; notes: string | null;
          provider: string; model_name: string; weekly_rate: number }
  current: Assignment | null
  assignments: Assignment[]
  maintenance: MaintRow[]
}

export function EvProfilePage() {
  const { id } = useParams<{ id: string }>()
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin' || user?.role === 'creator'
  const isCreator = user?.role === 'creator'
  const [profile, setProfile] = useState<Profile | null>(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    if (!id) return
    setBusy(true); setError(null)
    api.get<Profile>('/evs/' + encodeURIComponent(id) + '/profile')
      .then(setProfile)
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false))
  }
  useEffect(load, [id])

  if (busy && !profile) return <Spinner label="Loading…" />
  if (error || !profile) return <p className="text-red-600">{error ?? 'Not found'}</p>

  const u = profile.unit
  const cur = profile.current
  const openMaint = profile.maintenance.find((m) => m.to_date === null)

  return (
    <div className="max-w-6xl mx-auto">
      <Link to="/evs" className="text-sm text-brand underline">← Back to EVs</Link>
      <h1 className="text-2xl font-bold mt-2 mb-1">
        {u.ev_id} <span className="text-slate-400 text-base">— {u.provider} {u.model_name}</span>
      </h1>
      <div className="flex gap-2 items-center mb-6">
        <span className={'text-xs px-2 py-0.5 rounded ' + statusColor(u.status)}>{u.status}</span>
        <span className="text-sm text-slate-500">Weekly rate: {fmt(u.weekly_rate)}</span>
        {openMaint && (
          <span className="text-xs bg-amber-200 text-amber-900 px-2 py-0.5 rounded">
            in maintenance since {openMaint.from_date}
          </span>
        )}
      </div>


      <Section title="Current Holder">
        {cur ? (
          <div className="p-4 text-sm">
            <Link to={'/persons/' + cur.person_id}
                  className="text-brand underline font-semibold">
              {cur.display_name ?? '#' + cur.person_id}
            </Link>
            <div className="grid grid-cols-3 gap-y-1 mt-3 text-xs">
              <span className="text-slate-500">Handover</span>
              <span className="col-span-2">{cur.handover_date ?? '-'}</span>
              <span className="text-slate-500">Rent charged through</span>
              <span className="col-span-2">{cur.rent_charged_through ?? '-'}</span>
            </div>
          </div>
        ) : <p className="p-4 text-sm text-slate-500">EV is currently unassigned (spare).</p>}
      </Section>

      {isAdmin && (
        <div className="grid md:grid-cols-2 gap-4 mb-6">
          <AssignCard evId={u.ev_id} hasHolder={!!cur} onChanged={load} />
          <ReturnCard evId={u.ev_id} status={u.status} hasHolder={!!cur} onChanged={load} />
          <MaintenanceOpenCard evId={u.ev_id} disabled={!!openMaint} onLogged={load} />
          <MaintenanceCloseCard openRow={openMaint} onClosed={load} />
          <MarkSpareCard evId={u.ev_id} hasHolder={!!cur} onChanged={load} />
        </div>
      )}

      <Section title={`Assignment History (${profile.assignments.length})`}>
        <table className="w-full text-sm">
          <thead className="bg-slate-100 text-left">
            <tr><Th>Person</Th><Th>Handover</Th><Th>Returned</Th><Th>Rent through</Th></tr>
          </thead>
          <tbody>
            {profile.assignments.map((a) => (
              <tr key={a.assignment_id} className="border-t">
                <Td>
                  <Link to={'/persons/' + a.person_id} className="text-brand underline">
                    {a.display_name ?? '#' + a.person_id}
                  </Link>
                </Td>
                <Td>{a.handover_date ?? '-'}</Td>
                <Td>{a.returned_date ?? <span className="text-amber-700 font-medium">open</span>}</Td>
                <Td>{a.rent_charged_through ?? '-'}</Td>
              </tr>
            ))}
          </tbody>
        </table>
        {profile.assignments.length === 0 &&
          <p className="p-4 text-sm text-slate-500">No assignment history.</p>}
      </Section>

      <Section title={`Maintenance Log (${profile.maintenance.length})`}>
        <table className="w-full text-sm">
          <thead className="bg-slate-100 text-left">
            <tr><Th>ID</Th><Th>From</Th><Th>To</Th><Th>Reason</Th><Th>Logged by</Th><Th>When</Th></tr>
          </thead>
          <tbody>
            {profile.maintenance.map((m) => (
              <tr key={m.id} className={'border-t ' + (m.to_date === null ? 'bg-amber-50' : '')}>
                <Td>{m.id}</Td>
                <Td>{m.from_date}</Td>
                <Td>{m.to_date ?? <span className="text-amber-700 font-medium">still open</span>}</Td>
                <Td>{m.reason ?? ''}</Td>
                <Td className="text-xs">{m.created_by ?? ''}</Td>
                <Td className="text-xs">{m.created_at ?? ''}</Td>
              </tr>
            ))}
          </tbody>
        </table>
        {profile.maintenance.length === 0 &&
          <p className="p-4 text-sm text-slate-500">No maintenance windows logged.</p>}
      </Section>

      {isCreator && (
        <DangerZone
          kind="EV unit"
          label={u.ev_id}
          deletePath={`/api/creator/evs/${encodeURIComponent(u.ev_id)}`}
          onDeleted={() => { window.location.href = '/evs' }}
        />
      )}
    </div>
  )
}

function statusColor(s: string) {
  if (s === 'in_use') return 'bg-green-100'
  if (s === 'returned') return 'bg-slate-100'
  if (s === 'maintenance') return 'bg-amber-200'
  return 'bg-amber-100'
}

function AssignCard({ evId, hasHolder, onChanged }:
  { evId: string; hasHolder: boolean; onChanged: () => void }) {
  const empty = { rider_id: '', company: '', handover_date: '' }
  const [form, setForm] = useState(empty)
  const [busy, setBusy] = useState(false); const [msg, setMsg] = useState<string | null>(null)
  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setMsg(null)
    try {
      const body: Record<string, string> = {
        ev_id: evId, rider_id: form.rider_id, company: form.company,
      }
      if (form.handover_date) body.handover_date = form.handover_date
      await api.post('/evs/assign', body); setMsg('Assigned'); setForm(empty); onChanged()
    } catch (err) { setMsg(err instanceof Error ? err.message : 'Failed') }
    finally { setBusy(false) }
  }
  return <Card title={hasHolder ? 'Reassign EV (return first)' : 'Assign EV'}>
    <form onSubmit={submit} className="grid grid-cols-2 gap-2 text-sm">
      <In v={form.rider_id} on={(v) => setForm({ ...form, rider_id: v })} label="Rider ID *" />
      <In v={form.company} on={(v) => setForm({ ...form, company: v })} label="Company *" />
      <In v={form.handover_date} on={(v) => setForm({ ...form, handover_date: v })}
          label="Handover date" type="date" />
      <div />
      <button type="submit"
              disabled={busy || hasHolder || !form.rider_id || !form.company}
              className="col-span-2 bg-brand hover:bg-brand-700 text-white px-3 py-1.5 rounded disabled:opacity-50">
        {busy ? '…' : 'Assign'}
      </button>
      {msg && <span className="col-span-2 text-xs">{msg}</span>}
    </form>
  </Card>
}

function ReturnCard({ evId, status, hasHolder, onChanged }:
  { evId: string; status: string; hasHolder: boolean; onChanged: () => void }) {
  const [date, setDate] = useState('')
  const [busy, setBusy] = useState(false); const [msg, setMsg] = useState<string | null>(null)
  const canReturn = status !== 'returned'
  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setMsg(null)
    try {
      const body: Record<string, string> = { ev_id: evId }
      if (date) body.returned_date = date
      await api.post('/evs/return', body); setMsg('Returned'); setDate(''); onChanged()
    } catch (err) { setMsg(err instanceof Error ? err.message : 'Failed') }
    finally { setBusy(false) }
  }
  return <Card title="Return EV">
    <p className="text-xs text-slate-500 mb-2">
      {status === 'returned'
        ? 'This EV is already returned.'
        : hasHolder
          ? 'Retire this EV to the provider — closes the rider’s assignment (rent stops).'
          : 'Retire this spare EV to the provider.'}
    </p>
    <form onSubmit={submit} className="text-sm">
      <In v={date} on={setDate} label="Returned date (blank = today)" type="date" />
      <button type="submit" disabled={busy || !canReturn}
              className="mt-2 bg-brand hover:bg-brand-700 text-white px-3 py-1.5 rounded disabled:opacity-50">
        {busy ? '…' : 'Return'}
      </button>
      {msg && <span className="ml-2 text-xs">{msg}</span>}
    </form>
  </Card>
}

function MaintenanceOpenCard({ evId, disabled, onLogged }:
  { evId: string; disabled: boolean; onLogged: () => void }) {
  const empty = { from_date: '', to_date: '', reason: '' }
  const [form, setForm] = useState(empty)
  const [busy, setBusy] = useState(false); const [msg, setMsg] = useState<string | null>(null)
  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setMsg(null)
    try {
      const body: Record<string, string> = { ev_id: evId, from_date: form.from_date }
      if (form.to_date) body.to_date = form.to_date
      if (form.reason) body.reason = form.reason
      await api.post('/evs/maintenance', body); setForm(empty); setMsg('Logged'); onLogged()
    } catch (err) { setMsg(err instanceof Error ? err.message : 'Failed') }
    finally { setBusy(false) }
  }
  return <Card title="Log Maintenance">
    <form onSubmit={submit} className="grid grid-cols-2 gap-2 text-sm">
      <In v={form.from_date} on={(v) => setForm({ ...form, from_date: v })}
          label="From *" type="date" />
      <In v={form.to_date} on={(v) => setForm({ ...form, to_date: v })}
          label="To (optional)" type="date" />
      <In v={form.reason} on={(v) => setForm({ ...form, reason: v })} label="Reason" />
      <div />
      <button type="submit" disabled={busy || disabled || !form.from_date}
              className="col-span-2 bg-brand hover:bg-brand-700 text-white px-3 py-1.5 rounded disabled:opacity-50">
        {busy ? '…' : disabled ? 'Already in maintenance' : 'Log'}
      </button>
      {msg && <span className="col-span-2 text-xs">{msg}</span>}
    </form>
  </Card>
}

function MaintenanceCloseCard({ openRow, onClosed }:
  { openRow: MaintRow | undefined; onClosed: () => void }) {
  const [date, setDate] = useState('')
  const [busy, setBusy] = useState(false); const [msg, setMsg] = useState<string | null>(null)
  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!openRow) return
    setBusy(true); setMsg(null)
    try {
      const body: Record<string, string> = {}
      if (date) body.to_date = date
      await api.patch('/evs/maintenance/' + openRow.id, body)
      setMsg('Closed'); setDate(''); onClosed()
    } catch (err) { setMsg(err instanceof Error ? err.message : 'Failed') }
    finally { setBusy(false) }
  }
  return <Card title="Close Maintenance">
    <form onSubmit={submit} className="text-sm">
      {openRow ? (
        <>
          <p className="text-xs text-slate-500 mb-2">
            Open window since {openRow.from_date}. Leave date blank to close as of today.
          </p>
          <In v={date} on={setDate} label="Returned date" type="date" />
          <button type="submit" disabled={busy}
                  className="mt-2 bg-brand hover:bg-brand-700 text-white px-3 py-1.5 rounded disabled:opacity-50">
            {busy ? '…' : 'Close'}
          </button>
          {msg && <span className="ml-2 text-xs">{msg}</span>}
        </>
      ) : <p className="text-xs text-slate-500">No open maintenance window.</p>}
    </form>
  </Card>
}

function MarkSpareCard({ evId, hasHolder, onChanged }:
  { evId: string; hasHolder: boolean; onChanged: () => void }) {
  const [date, setDate] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setMsg(null)
    try {
      const body: Record<string, string> = { ev_id: evId }
      if (date) body.returned_date = date
      await api.post('/evs/to-spare', body); setMsg('Marked spare'); setDate(''); onChanged()
    } catch (err) { setMsg(err instanceof Error ? err.message : 'Failed') }
    finally { setBusy(false) }
  }
  return <Card title="Mark as Spare">
    <p className="text-xs text-slate-500 mb-2">
      {hasHolder
        ? 'Take this EV back from its rider into the spare pool — rent stops, but the EV stays available for reassignment (not retired).'
        : 'Only an EV currently with a rider can be marked spare.'}
    </p>
    <form onSubmit={submit} className="text-sm">
      <In v={date} on={setDate} label="Effective date (blank = today)" type="date" />
      <button type="submit" disabled={busy || !hasHolder}
              className="mt-2 bg-amber-500 hover:bg-amber-600 text-white px-3 py-1.5 rounded disabled:opacity-50">
        {busy ? '…' : 'Mark as Spare'}
      </button>
      {msg && <span className="ml-2 text-xs">{msg}</span>}
    </form>
  </Card>
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="mb-6">
    <h2 className="font-semibold mb-2">{title}</h2>
    <div className="bg-white/80 backdrop-blur-xl rounded-xl shadow-card transition-shadow duration-200 hover:shadow-glass overflow-x-auto">{children}</div>
  </section>
}
function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return <div className="bg-white/80 backdrop-blur-xl rounded-xl shadow-card transition-shadow duration-200 hover:shadow-glass p-4">
    <h3 className="font-semibold text-sm mb-2">{title}</h3>{children}
  </div>
}
function Th({ children }: { children: React.ReactNode }) {
  return <th className="px-3 py-2 font-medium text-xs">{children}</th>
}
function Td({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return <td className={'px-3 py-2 ' + className}>{children}</td>
}
function In({ v, on, label, type = 'text' }:
  { v: string; on: (v: string) => void; label: string; type?: string }) {
  return <label className="block">
    <span className="block text-xs text-slate-600">{label}</span>
    <input type={type} value={v} onChange={(e) => on(e.target.value)}
           className="w-full border rounded px-2 py-1" />
  </label>
}
