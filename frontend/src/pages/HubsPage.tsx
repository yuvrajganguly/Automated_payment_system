/**
 * Admin → Hubs — every store, per company: its zone (North / South / Misc)
 * and, for companies we pay ourselves, what that store pays when it differs
 * from the company default.
 *
 * Hubs are free text on rider rows (company files, onboarding), so a store
 * shows up here as soon as a rider has it; an admin can also add one ahead
 * of its first rider. A store with no zone is "unassigned" — its riders take
 * the zone of the recruiter who onboarded them until it is classified, and
 * hub-less riders (Blitz and co.) sit under "Misc" in the recruiter app.
 */
import { useLiveReload } from '../hooks/useLive'
import { FormEvent, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { Company } from '../api/types'
import { Spinner } from '../components/Spinner'
import { rupees } from '../lib/format'

type Zone = 'North' | 'South' | 'Misc'
const ZONES: Zone[] = ['North', 'South', 'Misc']
const ZONE_TONE: Record<Zone, string> = {
  North: 'bg-sky-500 text-white border-sky-500',
  South: 'bg-amber-500 text-white border-amber-500',
  Misc: 'bg-slate-500 text-white border-slate-500',
}

interface HubRow {
  company: string
  hub: string
  zone: Zone | null
  per_order_rate: number | null
  salary: number | null
  incentive_per_order: number | null
  incentive_per_day: number | null
  notes: string | null
  is_active: boolean
  riders: number
  evs: number
  payment_model: string | null
}

export function HubsPage() {
  const [params, setParams] = useSearchParams()
  const [rows, setRows] = useState<HubRow[]>([])
  const [companies, setCompanies] = useState<Company[]>([])
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const company = params.get('company') ?? ''

  const reload = () => {
    setBusy(true); setError(null)
    Promise.all([api.get<HubRow[]>('/hubs'), api.get<Company[]>('/companies')])
      .then(([h, c]) => { setRows(h); setCompanies(c) })
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false))
  }
  useEffect(reload, [])
  // Follow the server: stores change as riders arrive.
  useLiveReload(reload, ['hub', 'rider'])

  async function save(row: { company: string; hub: string }, body: Record<string, unknown>) {
    const key = row.company + '/' + row.hub
    setSaving(key); setError(null)
    try {
      await api.put('/hubs/' + encodeURIComponent(row.company) + '/' + encodeURIComponent(row.hub), body)
      reload()
    } catch (e) { setError(e instanceof Error ? e.message : 'Failed') }
    finally { setSaving(null) }
  }

  const needle = q.trim().toLowerCase()
  const shown = rows.filter((r) => (!company || r.company === company) && (!needle || r.hub.toLowerCase().includes(needle)))
  const byCompany = useMemo(() => {
    const m = new Map<string, HubRow[]>()
    for (const r of shown) m.set(r.company, [...(m.get(r.company) ?? []), r])
    return Array.from(m.entries()).sort((a, b) => b[1].reduce((n, x) => n + x.riders, 0) - a[1].reduce((n, x) => n + x.riders, 0))
  }, [shown])
  const unassigned = rows.filter((r) => !r.zone && r.is_active).length
  const count = (z: Zone) => rows.filter((r) => r.zone === z && r.is_active).length

  return (
    <div className="max-w-6xl mx-auto">
      <h1 className="text-2xl font-bold mb-1">Hubs</h1>
      <p className="text-slate-500 text-sm mb-4">
        Every store, per company. Set each one's zone — the recruiter app filters riders and the fleet by it
        and builds each recruiter's round from it. For companies we pay ourselves (per order, salary) a store
        can also carry its own rate, salary and incentives; blank means the company figure applies.
      </p>

      <div className="flex flex-wrap items-center gap-2 mb-4 text-xs">
        <span className="px-2 py-1 rounded bg-sky-500/15">North · {count('North')}</span>
        <span className="px-2 py-1 rounded bg-amber-500/15">South · {count('South')}</span>
        <span className="px-2 py-1 rounded bg-slate-500/15">Misc · {count('Misc')}</span>
        <span className={'px-2 py-1 rounded ' + (unassigned ? 'bg-red-500/15' : 'bg-slate-100')}>Unassigned · {unassigned}</span>
        <span className="ml-auto" />
        <select value={company} onChange={(e) => setParams(e.target.value ? { company: e.target.value } : {})}
                className="border rounded px-2 py-1 text-sm">
          <option value="">All companies</option>
          {companies.map((c) => <option key={c.company_name} value={c.company_name}>{c.company_name}</option>)}
        </select>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a hub…"
               className="border rounded px-3 py-1 text-sm w-48" />
      </div>

      <AddHubCard companies={companies} defaultCompany={company} busy={saving !== null} onAdd={(c, h, z) => save({ company: c, hub: h }, { zone: z })} />

      {busy && <Spinner />}
      {error && <p className="text-red-400 text-sm mb-3">{error}</p>}

      {byCompany.map(([co, hubs]) => {
        const model = hubs[0]?.payment_model ?? companies.find((c) => c.company_name === co)?.payment_model ?? 'payout_file'
        const perOrder = model === 'per_order'
        const salary = model === 'salary'
        return (
          <section key={co} className="mb-6">
            <h2 className="font-semibold mb-2 flex items-baseline gap-2">
              {co}
              <span className="text-xs text-slate-500 font-normal">
                {hubs.length} store{hubs.length === 1 ? '' : 's'} · {hubs.reduce((n, h) => n + h.riders, 0)} riders
                {perOrder && ' · paid per order'}{salary && ' · salaried'}
              </span>
            </h2>
            <div className="panel overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-slate-100 text-left">
                  <tr>
                    <th className="px-3 py-2">Hub</th>
                    <th className="px-3 py-2">Zone</th>
                    <th className="px-3 py-2 text-right">Riders</th>
                    <th className="px-3 py-2 text-right">EVs out</th>
                    {perOrder && <th className="px-3 py-2 text-right">₹ / order</th>}
                    {salary && <th className="px-3 py-2 text-right">Salary</th>}
                    {salary && <th className="px-3 py-2 text-right">₹ / order</th>}
                    {salary && <th className="px-3 py-2 text-right">₹ / day</th>}
                    <th className="px-3 py-2">Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {hubs.map((r) => (
                    <HubRowEditor key={r.company + '/' + r.hub} row={r} perOrder={perOrder} salary={salary}
                                  busy={saving === r.company + '/' + r.hub} onSave={(b) => save(r, b)} />
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )
      })}
      {!busy && byCompany.length === 0 && <p className="text-slate-500 text-sm">No stores match.</p>}
    </div>
  )
}

function HubRowEditor({ row, perOrder, salary, busy, onSave }:
  { row: HubRow; perOrder: boolean; salary: boolean; busy: boolean; onSave: (b: Record<string, unknown>) => void }) {
  const money = (k: 'per_order_rate' | 'salary' | 'incentive_per_order' | 'incentive_per_day') => (
    <td className="px-3 py-2 text-right">
      <MoneyCell value={row[k]} onCommit={(v) => onSave({ [k]: v })} disabled={busy} />
    </td>
  )
  return (
    <tr className={'border-t ' + (!row.zone ? 'bg-red-500/5' : '') + (!row.is_active ? ' opacity-50' : '')}>
      <td className="px-3 py-2 font-medium">{row.hub}{!row.is_active && <span className="ml-2 text-xs text-slate-400">inactive</span>}</td>
      <td className="px-3 py-2">
        <div className="flex gap-1 items-center">
          {ZONES.map((z) => (
            <button key={z} onClick={() => onSave({ zone: row.zone === z ? null : z })} disabled={busy}
              className={'text-xs px-2 py-0.5 rounded border ' + (row.zone === z ? ZONE_TONE[z] : 'hover:bg-slate-100')}>
              {z}
            </button>
          ))}
          {!row.zone && <span className="text-xs text-red-500 ml-1">unassigned</span>}
        </div>
      </td>
      <td className="px-3 py-2 text-right">{row.riders}</td>
      <td className="px-3 py-2 text-right">{row.evs}</td>
      {perOrder && money('per_order_rate')}
      {salary && money('salary')}
      {salary && money('incentive_per_order')}
      {salary && money('incentive_per_day')}
      <td className="px-3 py-2">
        <TextCell value={row.notes} onCommit={(v) => onSave({ notes: v })} disabled={busy} />
      </td>
    </tr>
  )
}

/** Click-to-edit rupee cell; blank = company default. */
function MoneyCell({ value, onCommit, disabled }: { value: number | null; onCommit: (v: number | null) => void; disabled: boolean }) {
  const [editing, setEditing] = useState(false)
  const [v, setV] = useState(value == null ? '' : String(value))
  useEffect(() => { setV(value == null ? '' : String(value)) }, [value])
  if (!editing) {
    return <button onClick={() => setEditing(true)} disabled={disabled} className="hover:underline text-right w-full" title="Edit — blank means the company figure">
      {value == null ? <span className="text-slate-400 text-xs">default</span> : rupees(value)}
    </button>
  }
  const commit = () => { setEditing(false); const n = v.trim() === '' ? null : Number(v.replace(/[^\d.]/g, '')); if (n !== value) onCommit(n) }
  return <input autoFocus value={v} onChange={(e) => setV(e.target.value)} onBlur={commit}
                onKeyDown={(e) => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') { setEditing(false); setV(value == null ? '' : String(value)) } }}
                className="border rounded px-2 py-0.5 text-xs w-24 text-right" inputMode="decimal" placeholder="default" />
}

function TextCell({ value, onCommit, disabled }: { value: string | null; onCommit: (v: string) => void; disabled: boolean }) {
  const [editing, setEditing] = useState(false)
  const [v, setV] = useState(value ?? '')
  useEffect(() => { setV(value ?? '') }, [value])
  if (!editing) {
    return <button onClick={() => setEditing(true)} disabled={disabled} className="hover:underline text-left text-xs w-full min-h-[1.25rem]">
      {value || <span className="text-slate-400">add</span>}
    </button>
  }
  const commit = () => { setEditing(false); if (v.trim() !== (value ?? '')) onCommit(v.trim()) }
  return <input autoFocus value={v} onChange={(e) => setV(e.target.value)} onBlur={commit}
                onKeyDown={(e) => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') { setEditing(false); setV(value ?? '') } }}
                className="border rounded px-2 py-0.5 text-xs w-48" />
}

function AddHubCard({ companies, defaultCompany, busy, onAdd }:
  { companies: Company[]; defaultCompany: string; busy: boolean; onAdd: (company: string, hub: string, zone: Zone) => void }) {
  const [company, setCompany] = useState(defaultCompany)
  const [hub, setHub] = useState('')
  const [zone, setZone] = useState<Zone>('North')
  useEffect(() => { if (defaultCompany) setCompany(defaultCompany) }, [defaultCompany])
  const submit = (e: FormEvent) => { e.preventDefault(); if (company && hub.trim()) { onAdd(company, hub.trim(), zone); setHub('') } }
  return (
    <form onSubmit={submit} className="panel p-3 mb-4 flex flex-wrap items-end gap-2 text-sm">
      <label className="block">
        <span className="text-xs text-slate-500">Add a store ahead of its first rider</span>
        <select value={company} onChange={(e) => setCompany(e.target.value)} className="block border rounded px-2 py-1 mt-0.5">
          <option value="">Company…</option>
          {companies.filter((c) => c.is_active).map((c) => <option key={c.company_name} value={c.company_name}>{c.company_name}</option>)}
        </select>
      </label>
      <input value={hub} onChange={(e) => setHub(e.target.value)} placeholder="e.g. New Town" className="border rounded px-2 py-1 w-56" />
      <select value={zone} onChange={(e) => setZone(e.target.value as Zone)} className="border rounded px-2 py-1">
        {ZONES.map((z) => <option key={z}>{z}</option>)}
      </select>
      <button type="submit" disabled={!company || !hub.trim() || busy} className="btn-primary !py-1 disabled:opacity-40">Add</button>
    </form>
  )
}
