import { FormEvent, useEffect, useState } from 'react'
import { useUrlString } from '../state/useUrlState'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Spinner } from '../components/Spinner'

const fmt = (n: number) =>
  n.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })

interface Stats {
  db_path: string
  db_size_bytes: number
  db_size_mb: number
  table_counts: Record<string, number>
  last_cycle_end: string | null
  last_audit_at: string | null
}

interface AuditRow {
  id: number
  at: string | null
  email: string | null
  role: string | null
  method: string
  path: string
  status_code: number | null
  duration_ms: number | null
  body_excerpt: string | null
  ip: string | null
}

type Tab = 'stats' | 'audit' | 'evmodels' | 'merge' | 'delete'

export function SystemPage() {
  const { user } = useAuth()
  const [tab, setTab] = useUrlString('tab', 'stats') as [Tab, (v: Tab) => void]

  if (user?.role !== 'creator') {
    return (
      <div className="max-w-xl mx-auto bg-amber-50 border border-amber-200 rounded p-6">
        <h1 className="font-bold mb-2">Creator-only</h1>
        <p className="text-sm text-amber-900">
          You need the Creator role to access System Control.
          Ask your existing creator to promote you on the Users page.
        </p>
      </div>
    )
  }

  return (
    <div className="max-w-7xl mx-auto">
      <h1 className="text-2xl font-bold mb-1">System Control</h1>
      <p className="text-slate-500 text-sm mb-6">
        Creator-only super-powers — every action you take here is recorded in
        the audit log automatically.
      </p>

      <div className="flex flex-wrap gap-2 mb-4">
        {([
          ['stats',    'Stats & Backup'],
          ['audit',    'Audit Log'],
          ['evmodels', 'EV Models'],
          ['merge',    'Force Merge'],
          ['delete',   'Hard Delete'],
        ] as [Tab, string][]).map(([k, label]) => (
          <button key={k} onClick={() => setTab(k)}
                  className={'text-sm px-3 py-1.5 rounded ' +
                    (tab === k ? 'bg-purple-600 text-white' : 'bg-slate-200 hover:bg-slate-300')}>
            {label}
          </button>
        ))}
      </div>

      {tab === 'stats'    && <StatsTab />}
      {tab === 'audit'    && <AuditTab />}
      {tab === 'evmodels' && <EvModelsTab />}
      {tab === 'merge'    && <ForceMergeTab />}
      {tab === 'delete'   && <HardDeleteTab />}
    </div>
  )
}

function StatsTab() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [busy, setBusy] = useState(true)
  useEffect(() => {
    api.get<Stats>('/creator/system/stats')
      .then(setStats).finally(() => setBusy(false))
  }, [])
  if (busy && !stats) return <Spinner />
  if (!stats) return <p className="text-red-600">Couldn't load stats.</p>
  return (
    <div className="grid md:grid-cols-2 gap-4">
      <div className="bg-white/80 backdrop-blur-xl rounded-xl shadow-card transition-shadow duration-200 hover:shadow-glass p-4">
        <h2 className="font-semibold mb-3">Database</h2>
        <dl className="grid grid-cols-2 gap-y-1 text-sm">
          <dt className="text-slate-500">Path</dt>
          <dd className="text-xs break-all">{stats.db_path}</dd>
          <dt className="text-slate-500">Size</dt><dd>{stats.db_size_mb} MB</dd>
          <dt className="text-slate-500">Last cycle</dt><dd>{stats.last_cycle_end ?? '-'}</dd>
          <dt className="text-slate-500">Last audit</dt><dd>{stats.last_audit_at ?? '-'}</dd>
        </dl>
        <a href="/api/creator/system/backup" download
           className="mt-4 inline-block bg-purple-600 hover:bg-purple-700 text-white px-3 py-1.5 rounded text-sm">
          ⬇ Download backup
        </a>
      </div>
      <div className="bg-white/80 backdrop-blur-xl rounded-xl shadow-card transition-shadow duration-200 hover:shadow-glass p-4 overflow-x-auto">
        <h2 className="font-semibold mb-3">Table sizes</h2>
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs">
            <tr><th className="px-2 py-1">Table</th><th className="px-2 py-1 text-right">Rows</th></tr>
          </thead>
          <tbody>
            {Object.entries(stats.table_counts)
              .sort((a, b) => b[1] - a[1])
              .map(([t, n]) => (
                <tr key={t} className="border-t">
                  <td className="px-2 py-1">{t}</td>
                  <td className="px-2 py-1 text-right">{fmt(n)}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function AuditTab() {
  const [rows, setRows] = useState<AuditRow[]>([])
  const [email, setEmail] = useState('')
  const [method, setMethod] = useState('')
  const [busy, setBusy] = useState(true)

  const reload = () => {
    setBusy(true)
    const p = new URLSearchParams({ limit: '300' })
    if (email) p.set('email', email)
    if (method) p.set('method', method)
    api.get<AuditRow[]>('/creator/audit-log?' + p)
      .then(setRows).finally(() => setBusy(false))
  }
  useEffect(reload, [email, method])

  return (
    <div>
      <div className="bg-white/80 backdrop-blur-xl rounded-xl shadow-card transition-shadow duration-200 hover:shadow-glass p-3 mb-3 flex flex-wrap gap-3">
        <label className="text-sm">
          <span className="block text-xs text-slate-500">Email</span>
          <input value={email} onChange={(e) => setEmail(e.target.value)}
                 placeholder="any" className="border rounded px-2 py-1 text-sm" />
        </label>
        <label className="text-sm">
          <span className="block text-xs text-slate-500">Method</span>
          <select value={method} onChange={(e) => setMethod(e.target.value)}
                  className="border rounded px-2 py-1 text-sm">
            <option value="">all</option>
            <option>POST</option><option>PATCH</option>
            <option>DELETE</option><option>PUT</option>
          </select>
        </label>
        <button onClick={reload}
                className="text-sm bg-slate-200 hover:bg-slate-300 px-3 py-1 rounded self-end">
          Refresh
        </button>
      </div>
      {busy && <Spinner />}
      <div className="bg-white/80 backdrop-blur-xl rounded-xl shadow-card transition-shadow duration-200 hover:shadow-glass overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="bg-slate-100 text-left">
            <tr>
              <th className="px-2 py-1">When</th>
              <th className="px-2 py-1">Who</th>
              <th className="px-2 py-1">Method</th>
              <th className="px-2 py-1">Path</th>
              <th className="px-2 py-1">Status</th>
              <th className="px-2 py-1">ms</th>
              <th className="px-2 py-1">Body excerpt</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-t hover:bg-slate-50">
                <td className="px-2 py-1 whitespace-nowrap">{r.at ?? ''}</td>
                <td className="px-2 py-1">
                  {r.email ?? <span className="text-slate-400">anon</span>}
                  {r.role && <span className="ml-1 text-[10px] text-slate-400">({r.role})</span>}
                </td>
                <td className="px-2 py-1 font-mono">{r.method}</td>
                <td className="px-2 py-1 font-mono text-[11px] break-all">{r.path}</td>
                <td className={'px-2 py-1 font-mono ' +
                  ((r.status_code ?? 0) >= 400 ? 'text-red-600' : 'text-slate-600')}>
                  {r.status_code}
                </td>
                <td className="px-2 py-1 text-right">{r.duration_ms ?? ''}</td>
                <td className="px-2 py-1 text-[11px] text-slate-500 break-all"
                    style={{ maxWidth: 320 }}>
                  {r.body_excerpt}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && !busy && (
          <p className="p-4 text-center text-slate-500 text-sm">No audit events yet.</p>
        )}
      </div>
    </div>
  )
}

function EvModelsTab() {
  interface Model { model_id: number; provider: string; model_name: string; weekly_rate: number }
  const [models, setModels] = useState<Model[]>([])
  const [busy, setBusy] = useState(true)
  const [form, setForm] = useState({ provider: '', model_name: '', weekly_rate: '' })

  const reload = () => {
    setBusy(true)
    api.get<Model[]>('/evs/models')
      .then(setModels).finally(() => setBusy(false))
  }
  useEffect(reload, [])

  async function add() {
    await api.post('/creator/ev-models', {
      provider: form.provider, model_name: form.model_name,
      weekly_rate: parseFloat(form.weekly_rate) || 0,
    })
    setForm({ provider: '', model_name: '', weekly_rate: '' })
    reload()
  }
  async function edit(m: Model, field: 'weekly_rate' | 'model_name' | 'provider', value: string | number) {
    const next: Model = { ...m, [field]: value }
    await fetch('/api/creator/ev-models/' + m.model_id, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        provider: next.provider, model_name: next.model_name,
        weekly_rate: next.weekly_rate,
      }),
    })
    reload()
  }
  async function del(model_id: number) {
    if (!confirm('Delete this EV model? Existing EVs using it will block deletion.')) return
    const r = await fetch('/api/creator/ev-models/' + model_id, {
      method: 'DELETE',
      credentials: 'include',
    })
    if (!r.ok) {
      const j = await r.json().catch(() => ({}))
      alert(j.detail ?? r.statusText)
    }
    reload()
  }

  return (
    <div>
      <div className="bg-white/80 backdrop-blur-xl rounded-xl shadow-card transition-shadow duration-200 hover:shadow-glass p-3 mb-3 flex flex-wrap gap-2 items-end">
        <Field label="Provider" v={form.provider} on={(v) => setForm({ ...form, provider: v })} />
        <Field label="Model name" v={form.model_name} on={(v) => setForm({ ...form, model_name: v })} />
        <Field label="Weekly rate" v={form.weekly_rate} on={(v) => setForm({ ...form, weekly_rate: v })} type="number" />
        <button onClick={add}
                disabled={!form.provider || !form.model_name || !form.weekly_rate}
                className="text-sm bg-purple-600 hover:bg-purple-700 text-white px-3 py-1.5 rounded disabled:opacity-50">
          Add model
        </button>
      </div>
      {busy && <Spinner />}
      <div className="bg-white/80 backdrop-blur-xl rounded-xl shadow-card transition-shadow duration-200 hover:shadow-glass overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-100 text-left">
            <tr>
              <th className="px-3 py-2 text-xs">ID</th>
              <th className="px-3 py-2 text-xs">Provider</th>
              <th className="px-3 py-2 text-xs">Model</th>
              <th className="px-3 py-2 text-xs">Weekly</th>
              <th className="px-3 py-2 text-xs">{''}</th>
            </tr>
          </thead>
          <tbody>
            {models.map((m) => (
              <tr key={m.model_id} className="border-t">
                <td className="px-3 py-2 text-xs">{m.model_id}</td>
                <td className="px-3 py-2">
                  <input defaultValue={m.provider}
                         onBlur={(e) => e.target.value !== m.provider && edit(m, 'provider', e.target.value)}
                         className="border rounded px-2 py-0.5 text-sm" />
                </td>
                <td className="px-3 py-2">
                  <input defaultValue={m.model_name}
                         onBlur={(e) => e.target.value !== m.model_name && edit(m, 'model_name', e.target.value)}
                         className="border rounded px-2 py-0.5 text-sm" />
                </td>
                <td className="px-3 py-2">
                  <input type="number" defaultValue={m.weekly_rate}
                         onBlur={(e) => parseFloat(e.target.value) !== m.weekly_rate &&
                                        edit(m, 'weekly_rate', parseFloat(e.target.value))}
                         className="border rounded px-2 py-0.5 text-sm w-24" />
                </td>
                <td className="px-3 py-2">
                  <button onClick={() => del(m.model_id)}
                          className="text-xs text-red-600 underline">delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ForceMergeTab() {
  const [primary, setPrimary] = useState('')
  const [secondary, setSecondary] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ tone: 'ok' | 'err'; text: string } | null>(null)

  async function go(e: FormEvent) {
    e.preventDefault(); setBusy(true); setMsg(null)
    try {
      await api.post('/creator/force-merge', {
        primary_person_id: parseInt(primary),
        secondary_person_id: parseInt(secondary),
      })
      setMsg({ tone: 'ok', text: `Merged #${secondary} into #${primary}.` })
      setPrimary(''); setSecondary('')
    } catch (e) {
      setMsg({ tone: 'err', text: e instanceof Error ? e.message : 'Failed' })
    } finally { setBusy(false) }
  }

  return (
    <form onSubmit={go} className="bg-white/80 backdrop-blur-xl rounded-xl shadow-card transition-shadow duration-200 hover:shadow-glass p-4 max-w-xl">
      <p className="text-xs text-amber-700 mb-3">
        ⚠ Bypasses the regular merge's open-EV check. Secondary's open
        assignment is closed as of today before the move.
      </p>
      <div className="grid grid-cols-2 gap-2 mb-3">
        <Field label="Primary Person ID" v={primary} on={setPrimary} type="number" />
        <Field label="Secondary Person ID" v={secondary} on={setSecondary} type="number" />
      </div>
      <button type="submit" disabled={busy || !primary || !secondary || primary === secondary}
              className="bg-purple-600 hover:bg-purple-700 text-white px-3 py-1.5 rounded disabled:opacity-50">
        {busy ? '…' : 'Force merge'}
      </button>
      {msg && <p className={'text-xs mt-2 ' + (msg.tone === 'err' ? 'text-red-600' : 'text-green-700')}>{msg.text}</p>}
    </form>
  )
}

function HardDeleteTab() {
  return (
    <div className="grid md:grid-cols-3 gap-4">
      <DeleteCard
        title="Person"
        prompt="Person ID"
        path="/persons/"
        warning="Cascade-purges rider_master rows, transactions, balances, ev_arrears, ev_assignments, COD holds, payment_lines, status_tracking. Irreversible." />
      <DeleteCard
        title="EV unit"
        prompt="EV ID"
        path="/evs/"
        warning="Drops the unit + every assignment and maintenance window. Open ev_assignments are deleted with no return-date adjustment." />
      <DeleteCard
        title="Company"
        prompt="Company name"
        path="/companies/"
        force
        warning="Drops parser config. With force=true also drops every transaction, COD hold, and rider_master row in that company." />
    </div>
  )
}

function DeleteCard({ title, prompt, path, warning, force }:
  { title: string; prompt: string; path: string; warning: string; force?: boolean }) {
  const [value, setValue] = useState('')
  const [useForce, setUseForce] = useState(false)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ tone: 'ok' | 'err'; text: string } | null>(null)

  async function go() {
    if (!confirm(`Hard-delete ${title} "${value}"? This cannot be undone.`)) return
    setBusy(true); setMsg(null)
    try {
      const url = '/api/creator' + path + encodeURIComponent(value)
                + (force && useForce ? '?force=true' : '')
      const r = await fetch(url, {
        method: 'DELETE',
        credentials: 'include',
      })
      const j = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(j.detail ?? r.statusText)
      setMsg({ tone: 'ok', text: `Deleted.` })
      setValue('')
    } catch (e) {
      setMsg({ tone: 'err', text: e instanceof Error ? e.message : 'Failed' })
    } finally { setBusy(false) }
  }

  return (
    <div className="bg-white/80 backdrop-blur-xl rounded-xl shadow-card transition-shadow duration-200 hover:shadow-glass p-4 border-l-4 border-red-400">
      <h3 className="font-semibold text-sm mb-1">{title}</h3>
      <p className="text-[11px] text-amber-700 mb-2">{warning}</p>
      <input value={value} onChange={(e) => setValue(e.target.value)}
             placeholder={prompt}
             className="w-full border rounded px-2 py-1 text-sm mb-2" />
      {force && (
        <label className="flex items-center gap-1 text-xs text-slate-600 mb-2">
          <input type="checkbox" checked={useForce} onChange={(e) => setUseForce(e.target.checked)} />
          force (drop all child rows too)
        </label>
      )}
      <button onClick={go} disabled={!value || busy}
              className="bg-red-600 hover:bg-red-700 text-white text-sm px-3 py-1.5 rounded disabled:opacity-50">
        {busy ? '…' : 'Hard delete'}
      </button>
      {msg && <p className={'text-xs mt-2 ' + (msg.tone === 'err' ? 'text-red-600' : 'text-green-700')}>{msg.text}</p>}
    </div>
  )
}

function Field({ label, v, on, type = 'text' }:
  { label: string; v: string; on: (v: string) => void; type?: string }) {
  return <label className="text-sm">
    <span className="block text-xs text-slate-600">{label}</span>
    <input type={type} value={v} onChange={(e) => on(e.target.value)}
           className="border rounded px-2 py-1 text-sm w-40" />
  </label>
}
