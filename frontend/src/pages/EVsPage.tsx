import { FormEvent, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Spinner } from '../components/Spinner'
import { ColumnFilters, applyFilters } from '../components/TableFilters'
import { useUrlRecord, useUrlString, useUrlList } from '../state/useUrlState'
import { ExportButton } from '../components/ExportButton'
import { SortableTh, useSort } from '../components/Sortable'
import type { EvModelOut, EvUnitOut, MaintenanceOut } from '../api/types'

const fmt = (n: number) => n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })

export function EVsPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin' || user?.role === 'creator'
  const [models, setModels] = useState<EvModelOut[]>([])
  const [units, setUnits] = useState<EvUnitOut[]>([])
  const [maint, setMaint] = useState<MaintenanceOut[]>([])
  const [unitFilters, setUnitFilters] = useUrlRecord('f')
  const [unitSearch, setUnitSearch] = useUrlString('q')
  const [hubFilter, setHubFilter] = useUrlList('hub')
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const hubOptions = Array.from(new Set(
    units.flatMap((u) => (u.hub ?? '').split(',').map((h) => h.trim()).filter(Boolean)),
  )).sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }))
  const toggleHub = (h: string) =>
    setHubFilter((s) => (s.includes(h) ? s.filter((x) => x !== h) : [...s, h]))
  const hubFiltered = hubFilter.length === 0 ? units : units.filter((u) =>
    (u.hub ?? '').split(',').map((h) => h.trim()).some((h) => hubFilter.includes(h)))
  const filteredUnits = applyFilters(hubFiltered, unitFilters)
  const q = unitSearch.trim().toLowerCase()
  const searchedUnits = q ? filteredUnits.filter((u) =>
    [u.ev_id, u.current_rider_name, u.current_rider_id, u.provider, u.model, u.status, u.hub]
      .some((v) => (v ?? '').toString().toLowerCase().includes(q))
  ) : filteredUnits
  const { sorted: visibleUnits, sortKey, sortDir, toggleSort } = useSort(searchedUnits, { urlKey: 'sort' })

  const reload = () => {
    setBusy(true); setError(null)
    Promise.all([
      api.get<EvModelOut[]>('/evs/models'),
      api.get<EvUnitOut[]>('/evs'),
      api.get<MaintenanceOut[]>('/evs/maintenance'),
    ]).then(([m, u, mt]) => { setModels(m); setUnits(u); setMaint(mt) })
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false))
  }
  useEffect(reload, [])

  return (
    <div className="max-w-7xl mx-auto">
      <div className="flex items-start justify-between gap-3 mb-1">
        <h1 className="text-2xl font-bold">EVs</h1>
        <ExportButton path="/evs/export" name="ev_units.xlsx" ids={visibleUnits.map((u) => u.ev_id)} />
      </div>
      <p className="text-slate-500 text-sm mb-6">Rate card, current units, assignments, and maintenance history.</p>
      {busy && <Spinner />}
      {error && <p className="text-red-600 text-sm mb-3">{error}</p>}

      <Section title="Rate Card">
        <table className="w-full text-sm">
          <thead className="bg-slate-100 text-left">
            <tr><Th>Provider</Th><Th>Model</Th><Th right>Weekly</Th><Th right>Daily (÷7)</Th></tr>
          </thead>
          <tbody>
            {models.map((m) => (
              <tr key={m.model_id} className="border-t">
                <Td>{m.provider}</Td><Td>{m.model_name}</Td>
                <Td right>{fmt(m.weekly_rate)}</Td>
                <Td right>{fmt(m.weekly_rate / 7)}</Td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <div className="mb-3">
        <input value={unitSearch} onChange={(e) => setUnitSearch(e.target.value)}
               placeholder="Search by EV ID, rider, provider, model, status…"
               className="w-full border rounded px-3 py-2 text-sm" />
      </div>
      <ColumnFilters
        rows={units}
        columns={[
          { key: 'provider', label: 'Provider' },
          { key: 'model',    label: 'Model' },
          { key: 'status',   label: 'Status' },
        ]}
        filters={unitFilters}
        onChange={setUnitFilters}
      />
      {hubOptions.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 mb-3">
          <span className="text-xs font-medium text-slate-500 mr-1">Hubs:</span>
          <button
            onClick={() => setHubFilter([])}
            className={'text-xs px-2 py-1 rounded ' +
              (hubFilter.length === 0 ? 'bg-brand text-white' : 'bg-slate-200 hover:bg-slate-300')}>
            All
          </button>
          {hubOptions.map((h) => (
            <button key={h} onClick={() => toggleHub(h)}
              className={'text-xs px-2 py-1 rounded ' +
                (hubFilter.includes(h) ? 'bg-brand text-white' : 'bg-slate-200 hover:bg-slate-300')}>
              {h}
            </button>
          ))}
          {hubFilter.length > 0 &&
            <span className="text-xs text-slate-400 ml-1">({hubFilter.length} selected)</span>}
        </div>
      )}
      <Section title={`EV Units (${visibleUnits.length} of ${units.filter((u) => u.status !== 'returned').length} active)`}>
        <table className="w-full text-sm">
          <thead className="bg-slate-100 text-left">
            <tr>
              <SortableTh tag="ev_id"        sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>EV ID</SortableTh>
              <SortableTh tag="provider"     sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Provider</SortableTh>
              <SortableTh tag="model"        sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Model</SortableTh>
              <SortableTh tag="weekly_rate"  sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} right>Weekly</SortableTh>
              <SortableTh tag="status"       sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Status</SortableTh>
              <SortableTh tag="current_rider_id" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Current Rider</SortableTh>
              <SortableTh tag="hub" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Hub</SortableTh>
              <SortableTh tag="handover_date" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Handover</SortableTh>
              <SortableTh tag="rent_charged_through" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Rent Through</SortableTh>
              <Th>Person</Th>
            </tr>
          </thead>
          <tbody>
            {visibleUnits.map((u) => (
              <tr key={u.ev_id} className="border-t">
                <Td><Link to={'/evs/' + encodeURIComponent(u.ev_id)}
                          className="text-brand underline">{u.ev_id}</Link></Td>
                <Td>{u.provider}</Td>
                <Td>{u.model}</Td>
                <Td right>{fmt(u.weekly_rate)}</Td>
                <Td>
                  <span className={'px-1.5 py-0.5 rounded text-xs ' +
                    (u.status === 'in_use' ? 'bg-green-100' : u.status === 'returned' ? 'bg-slate-100' : 'bg-amber-100')}>
                    {u.status}
                  </span>
                </Td>
                <Td>
                  {u.current_person_id ? (
                    <Link to={'/persons/' + u.current_person_id} className="text-brand underline">
                      {u.current_rider_name ?? '#' + u.current_person_id}
                    </Link>
                  ) : '-'}
                  {u.current_rider_id && (
                    <span className="block text-xs text-slate-500">{u.current_rider_id}</span>
                  )}
                </Td>
                <Td>{u.hub || '-'}</Td>
                <Td>{u.handover_date ?? '-'}</Td>
                <Td>{u.rent_charged_through ?? '-'}</Td>
                <Td>{u.current_person_id
                      ? <Link to={'/persons/' + u.current_person_id} className="text-brand underline">#{u.current_person_id}</Link>
                      : '-'}</Td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title={'Maintenance Log (' + maint.length + ')'}>
        <table className="w-full text-sm">
          <thead className="bg-slate-100 text-left">
            <tr><Th>EV</Th><Th>From</Th><Th>To</Th><Th>Reason</Th><Th>Logged By</Th><Th>When</Th></tr>
          </thead>
          <tbody>
            {maint.map((m) => (
              <tr key={m.id} className="border-t">
                <Td>{m.ev_id}</Td>
                <Td>{m.from_date}</Td>
                <Td>{m.to_date}</Td>
                <Td>{m.reason ?? ''}</Td>
                <Td className="text-xs">{m.created_by ?? ''}</Td>
                <Td className="text-xs">{m.created_at ?? ''}</Td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      {isAdmin && (
        <div className="grid md:grid-cols-2 gap-4">
          <AddEvCard models={models} onAdded={reload} />
          <AssignEvCard onChanged={reload} />
          <ReturnEvCard onChanged={reload} />
          <MarkSpareEvCard onChanged={reload} />
          <MaintenanceCard onLogged={reload} />
        </div>
      )}
    </div>
  )
}

function AddEvCard({ models, onAdded }: { models: EvModelOut[]; onAdded: () => void }) {
  const empty = { ev_id: '', provider: '', model: '', notes: '',
                  rider_id: '', company: '', handover_date: '' }
  const [form, setForm] = useState(empty)
  const [busy, setBusy] = useState(false); const [msg, setMsg] = useState<string | null>(null)
  const providers = Array.from(new Set(models.map((m) => m.provider)))
  const modelsFor = (p: string) => models.filter((m) => m.provider === p).map((m) => m.model_name)

  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setMsg(null)
    try {
      // 1. Create the unit
      await api.post('/evs', {
        ev_id: form.ev_id, provider: form.provider,
        model: form.model, notes: form.notes,
      })
      // 2. If a rider was given, immediately assign it
      if (form.rider_id && form.company) {
        const assignBody: Record<string, string> = {
          ev_id: form.ev_id, rider_id: form.rider_id, company: form.company,
        }
        if (form.handover_date) assignBody.handover_date = form.handover_date
        await api.post('/evs/assign', assignBody)
        setMsg('Added & assigned')
      } else {
        setMsg('Added (no rider; sits as spare)')
      }
      setForm(empty); onAdded()
    } catch (err) {
      setMsg(err instanceof Error ? err.message : 'Failed')
    }
    finally { setBusy(false) }
  }
  return <FormCard title="Add EV Unit">
    <form onSubmit={submit} className="grid grid-cols-2 gap-2 text-sm">
      <Input label="EV ID *" v={form.ev_id} on={(v) => setForm({ ...form, ev_id: v })} />
      <SelectF label="Provider *" v={form.provider}
               on={(v) => setForm({ ...form, provider: v, model: '' })}
               options={['', ...providers]} />
      <SelectF label="Model *" v={form.model} on={(v) => setForm({ ...form, model: v })}
               options={['', ...modelsFor(form.provider)]} />
      <Input label="Notes" v={form.notes} on={(v) => setForm({ ...form, notes: v })} />
      <div className="col-span-2 mt-2 -mb-1 pt-2 border-t border-slate-200 text-xs text-slate-500">
        Optional: bind to a rider right away
      </div>
      <Input label="Rider ID (system internal)" v={form.rider_id}
             on={(v) => setForm({ ...form, rider_id: v })} />
      <Input label="Company" v={form.company}
             on={(v) => setForm({ ...form, company: v })} />
      <Input label="Handover date" type="date" v={form.handover_date}
             on={(v) => setForm({ ...form, handover_date: v })} />
      <div />
      <div className="col-span-2 flex gap-2 items-center"><Submit busy={busy}
        disabled={!form.ev_id || !form.provider || !form.model
                  || (form.rider_id !== '' && form.company === '')
                  || (form.company !== '' && form.rider_id === '')}
        label="Add" />{msg && <span className="text-xs">{msg}</span>}</div>
    </form>
  </FormCard>
}

function AssignEvCard({ onChanged }: { onChanged: () => void }) {
  const empty = { ev_id: '', rider_id: '', company: '', handover_date: '' }
  const [form, setForm] = useState(empty)
  const [busy, setBusy] = useState(false); const [msg, setMsg] = useState<string | null>(null)
  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setMsg(null)
    try {
      const body: Record<string, string> = { ev_id: form.ev_id, rider_id: form.rider_id, company: form.company }
      if (form.handover_date) body.handover_date = form.handover_date
      await api.post('/evs/assign', body); setMsg('Assigned'); setForm(empty); onChanged()
    } catch (err) { setMsg(err instanceof Error ? err.message : 'Failed') }
    finally { setBusy(false) }
  }
  return <FormCard title="Assign EV">
    <form onSubmit={submit} className="grid grid-cols-2 gap-2 text-sm">
      <Input label="EV ID *" v={form.ev_id} on={(v) => setForm({ ...form, ev_id: v })} />
      <Input label="Rider ID *" v={form.rider_id} on={(v) => setForm({ ...form, rider_id: v })} />
      <Input label="Company *" v={form.company} on={(v) => setForm({ ...form, company: v })} />
      <Input label="Handover date" type="date" v={form.handover_date} on={(v) => setForm({ ...form, handover_date: v })} />
      <div className="col-span-2 flex gap-2 items-center"><Submit busy={busy}
        disabled={!form.ev_id || !form.rider_id || !form.company} label="Assign" />{msg && <span className="text-xs">{msg}</span>}</div>
    </form>
  </FormCard>
}

function ReturnEvCard({ onChanged }: { onChanged: () => void }) {
  const empty = { ev_id: '', rider_id: '', company: '', returned_date: '' }
  const [form, setForm] = useState(empty)
  const [busy, setBusy] = useState(false); const [msg, setMsg] = useState<string | null>(null)
  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setMsg(null)
    try {
      const body: Record<string, string> = {}
      if (form.ev_id) body.ev_id = form.ev_id
      if (form.rider_id) body.rider_id = form.rider_id
      if (form.company) body.company = form.company
      if (form.returned_date) body.returned_date = form.returned_date
      await api.post('/evs/return', body); setMsg('Returned'); setForm(empty); onChanged()
    } catch (err) { setMsg(err instanceof Error ? err.message : 'Failed') }
    finally { setBusy(false) }
  }
  // Either an EV ID alone, or rider_id + company together.
  const validEv  = !!form.ev_id
  const validRid = !!form.rider_id && !!form.company
  return <FormCard title="Return EV">
    <form onSubmit={submit} className="grid grid-cols-2 gap-2 text-sm">
      <Input label="EV ID" v={form.ev_id} on={(v) => setForm({ ...form, ev_id: v })} />
      <div />
      <Input label="Rider ID" v={form.rider_id} on={(v) => setForm({ ...form, rider_id: v })} />
      <Input label="Company" v={form.company} on={(v) => setForm({ ...form, company: v })} />
      <Input label="Returned date" type="date" v={form.returned_date}
             on={(v) => setForm({ ...form, returned_date: v })} />
      <div className="col-span-2 text-xs text-slate-500 -mt-1">
        Retires the EV to the provider — works for an assigned EV or a spare. Give the EV ID or (Rider ID + Company).
      </div>
      <div className="col-span-2 flex gap-2 items-center"><Submit busy={busy}
        disabled={!validEv && !validRid} label="Return" />{msg && <span className="text-xs">{msg}</span>}</div>
    </form>
  </FormCard>
}

function MarkSpareEvCard({ onChanged }: { onChanged: () => void }) {
  const empty = { ev_id: '', rider_id: '', company: '', returned_date: '' }
  const [form, setForm] = useState(empty)
  const [busy, setBusy] = useState(false); const [msg, setMsg] = useState<string | null>(null)
  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setMsg(null)
    try {
      const body: Record<string, string> = {}
      if (form.ev_id) body.ev_id = form.ev_id
      if (form.rider_id) body.rider_id = form.rider_id
      if (form.company) body.company = form.company
      if (form.returned_date) body.returned_date = form.returned_date
      await api.post('/evs/to-spare', body); setMsg('Marked spare'); setForm(empty); onChanged()
    } catch (err) { setMsg(err instanceof Error ? err.message : 'Failed') }
    finally { setBusy(false) }
  }
  const validEv  = !!form.ev_id
  const validRid = !!form.rider_id && !!form.company
  return <FormCard title="Mark EV as Spare">
    <form onSubmit={submit} className="grid grid-cols-2 gap-2 text-sm">
      <Input label="EV ID" v={form.ev_id} on={(v) => setForm({ ...form, ev_id: v })} />
      <div />
      <Input label="Rider ID" v={form.rider_id} on={(v) => setForm({ ...form, rider_id: v })} />
      <Input label="Company" v={form.company} on={(v) => setForm({ ...form, company: v })} />
      <Input label="Effective date" type="date" v={form.returned_date}
             on={(v) => setForm({ ...form, returned_date: v })} />
      <div className="col-span-2 text-xs text-slate-500 -mt-1">
        Takes an EV back from its rider into the spare pool — rent stops, EV stays available for reassignment. Give the EV ID or (Rider ID + Company).
      </div>
      <div className="col-span-2 flex gap-2 items-center"><Submit busy={busy}
        disabled={!validEv && !validRid} label="Mark as Spare" />{msg && <span className="text-xs">{msg}</span>}</div>
    </form>
  </FormCard>
}

function MaintenanceCard({ onLogged }: { onLogged: () => void }) {
  const empty = { ev_id: '', from_date: '', to_date: '', reason: '' }
  const [form, setForm] = useState(empty)
  const [busy, setBusy] = useState(false); const [msg, setMsg] = useState<string | null>(null)
  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setMsg(null)
    try {
      // Strip empty optional fields so the backend treats to_date as "open".
      const body: Record<string, string> = {
        ev_id: form.ev_id, from_date: form.from_date,
      }
      if (form.to_date) body.to_date = form.to_date
      if (form.reason) body.reason = form.reason
      await api.post('/evs/maintenance', body)
      setForm(empty); setMsg('Logged'); onLogged()
    }
    catch (err) { setMsg(err instanceof Error ? err.message : 'Failed') }
    finally { setBusy(false) }
  }
  return <FormCard title="Log Maintenance">
    <form onSubmit={submit} className="grid grid-cols-2 gap-2 text-sm">
      <Input label="EV ID *" v={form.ev_id} on={(v) => setForm({ ...form, ev_id: v })} />
      <Input label="From *" type="date" v={form.from_date} on={(v) => setForm({ ...form, from_date: v })} />
      <Input label="To (optional)" type="date" v={form.to_date} on={(v) => setForm({ ...form, to_date: v })} />
      <Input label="Reason" v={form.reason} on={(v) => setForm({ ...form, reason: v })} />
      <div className="col-span-2 text-xs text-slate-500 -mt-1">
        Leave To blank if you don't know when it'll be back. Close the window later from the EV's profile page.
      </div>
      <div className="col-span-2 flex gap-2 items-center"><Submit busy={busy}
        disabled={!form.ev_id || !form.from_date} label="Log" />{msg && <span className="text-xs">{msg}</span>}</div>
    </form>
  </FormCard>
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="mb-6">
    <h2 className="font-semibold mb-2">{title}</h2>
    <div className="bg-white/80 backdrop-blur-xl rounded-xl shadow-card transition-shadow duration-200 hover:shadow-glass overflow-x-auto">{children}</div>
  </section>
}
function FormCard({ title, children }: { title: string; children: React.ReactNode }) {
  return <div className="bg-white/80 backdrop-blur-xl rounded-xl shadow-card transition-shadow duration-200 hover:shadow-glass p-4"><h3 className="font-semibold mb-2 text-sm">{title}</h3>{children}</div>
}
function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return <th className={'px-3 py-2 font-medium text-xs ' + (right ? 'text-right' : '')}>{children}</th>
}
function Td({ children, right, className = '' }: { children: React.ReactNode; right?: boolean; className?: string }) {
  return <td className={'px-3 py-2 ' + (right ? 'text-right ' : '') + className}>{children}</td>
}
function Input({ label, v, on, type = 'text' }: { label: string; v: string; on: (v: string) => void; type?: string }) {
  return <label className="block"><span className="block text-xs text-slate-600">{label}</span>
    <input type={type} value={v} onChange={(e) => on(e.target.value)} className="w-full border rounded px-2 py-1" /></label>
}
function SelectF({ label, v, on, options }: { label: string; v: string; on: (v: string) => void; options: string[] }) {
  return <label className="block"><span className="block text-xs text-slate-600">{label}</span>
    <select value={v} onChange={(e) => on(e.target.value)} className="w-full border rounded px-2 py-1">
      {options.map((o) => <option key={o} value={o}>{o || '(none)'}</option>)}
    </select></label>
}
function Submit({ busy, disabled, label }: { busy: boolean; disabled?: boolean; label: string }) {
  return <button type="submit" disabled={busy || disabled}
    className="bg-brand hover:bg-brand-700 text-white px-3 py-1.5 rounded disabled:opacity-50">{busy ? '…' : label}</button>
}
