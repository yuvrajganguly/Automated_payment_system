import { FormEvent, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Spinner } from '../components/Spinner'
import { ColumnFilters, applyFilters } from '../components/TableFilters'
import { useUrlRecord, useUrlString } from '../state/useUrlState'
import { ExportButton } from '../components/ExportButton'
import { SortableTh, useSort } from '../components/Sortable'
import type { Company, RiderOut } from '../api/types'

export function RidersPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin' || user?.role === 'creator'
  const [riders, setRiders] = useState<RiderOut[]>([])
  const [companies, setCompanies] = useState<Company[]>([])
  const [filters, setFilters] = useUrlRecord('f')
  const [search, setSearch] = useUrlString('q')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => { api.get<Company[]>('/companies').then(setCompanies).catch(() => {}) }, [])

  // Fetch every rider once; spreadsheet-style filters work client-side.
  const reload = () => {
    setBusy(true); setError(null)
    api.get<RiderOut[]>('/riders')
      .then(setRiders)
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false))
  }
  useEffect(reload, [])

  // Apply company filter first so Hub options shrink to that company.
  const companyKey = filters['company'] ?? ''
  const scoped = companyKey ? riders.filter((r) => r.company === companyKey) : riders
  // Drop 'company' from the rest so we don't filter twice, then apply remaining.
  const restFilters = Object.fromEntries(Object.entries(filters).filter(([k]) => k !== 'company'))
  const filtered = applyFilters(scoped, restFilters)
  const q = search.trim().toLowerCase()
  const searched = q ? filtered.filter((r) =>
    [r.rider_id, r.name, r.hub, r.account_no, r.ifsc, r.mob_no, String(r.person_id)]
      .some((v) => (v ?? '').toString().toLowerCase().includes(q))
  ) : filtered
  const { sorted: visibleRiders, sortKey, sortDir, toggleSort } = useSort(searched, { urlKey: 'sort' })

  return (
    <div className="max-w-7xl mx-auto">
      <div className="flex items-start justify-between gap-3 mb-1">
        <h1 className="text-2xl font-bold">Riders</h1>
        <ExportButton path="/riders/export" name="riders.xlsx" ids={visibleRiders.map((r) => r.rider_id + '|' + r.company)} />
      </div>
      <p className="text-slate-500 text-sm mb-6">Browse the roster. Click a Person ID to open the full profile.</p>

      <div className="mb-3">
        <input value={search} onChange={(e) => setSearch(e.target.value)}
               placeholder="Search by name, rider ID, hub, account, IFSC, or person ID…"
               className="w-full border rounded px-3 py-2 text-sm" />
      </div>
      <ColumnFilters
        rows={riders}
        columns={[
          { key: 'company', label: 'Company' },
          { key: 'hub',     label: 'Hub' },
          { key: 'vehicle', label: 'Vehicle' },
        ]}
        filters={filters}
        onChange={setFilters}
      />
      <p className="text-xs text-slate-500 mb-3">
        Showing {visibleRiders.length} of {riders.length} riders. {busy && <Spinner />}
      </p>

      {error && <p className="text-red-600 text-sm mb-3">{error}</p>}

      <div className="bg-white/80 backdrop-blur-xl rounded-xl shadow-card transition-shadow duration-200 hover:shadow-glass overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-100 text-left">
            <tr>
              <SortableTh tag="person_id" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Person</SortableTh>
              <SortableTh tag="rider_id"  sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Rider ID</SortableTh>
              <SortableTh tag="name"      sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Name</SortableTh>
              <SortableTh tag="company"   sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Company</SortableTh>
              <SortableTh tag="hub"       sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Hub</SortableTh>
              <SortableTh tag="vehicle"   sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Vehicle</SortableTh>
              <Th>Account</Th><Th>IFSC</Th><Th>Phone</Th>
              <SortableTh tag="is_active" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>Active</SortableTh>
            </tr>
          </thead>
          <tbody>
            {visibleRiders.map((r) => (
              <tr key={r.rider_id + ':' + r.company} className="border-t hover:bg-slate-50">
                <Td><Link to={'/persons/' + r.person_id} className="text-brand underline">#{r.person_id}</Link></Td>
                <Td>{r.rider_id}</Td>
                <Td>{r.name}</Td>
                <Td>{r.company}</Td>
                <Td>{r.hub ?? '-'}</Td>
                <Td>{r.vehicle ?? '-'}</Td>
                <Td>{r.account_no ?? '-'}</Td>
                <Td>{r.ifsc ?? '-'}</Td>
                <Td>{r.mob_no ?? '-'}</Td>
                <Td>{r.is_active ? 'yes' : 'no'}</Td>
              </tr>
            ))}
          </tbody>
        </table>
        {riders.length === 0 && !busy && (
          <p className="p-6 text-center text-slate-500 text-sm">No riders match these filters.</p>
        )}
      </div>

      {isAdmin && (
        <div className="mt-6 grid md:grid-cols-2 gap-4">
          <AddRiderCard companies={companies} onAdded={reload} />
          <BulkUploadCard onUploaded={reload} />
          <BulkUpdateCard onUpdated={reload} />
          <LinkRidersCard onLinked={reload} />
        </div>
      )}
    </div>
  )
}

function AddRiderCard({ companies, onAdded }: { companies: Company[]; onAdded: () => void }) {
  const [open, setOpen] = useState(false)
  const empty = { rider_id: '', company: '', name: '', hub: '', vehicle: '', account_no: '', ifsc: '', mob_no: '' }
  const [form, setForm] = useState(empty)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [msgTone, setMsgTone] = useState<'ok' | 'err'>('ok')

  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setMsg(null)
    try {
      const r = await api.post<{ rider_id: string }>('/riders', form)
      setMsgTone('ok'); setMsg(`Added (rider_id=${r.rider_id})`)
      setForm(empty); onAdded()
    }
    catch (err) {
      setMsgTone('err')
      setMsg(err instanceof Error ? err.message : 'Failed')
    }
    finally { setBusy(false) }
  }
  return (
    <Card title="Add Rider" open={open} onToggle={() => setOpen(!open)}>
      <form onSubmit={submit} className="grid grid-cols-2 gap-2">
        <Input label="Rider ID (optional)" v={form.rider_id}
               on={(v) => setForm({ ...form, rider_id: v })} />
        <SelectF label="Company *" v={form.company}
                 on={(v) => setForm({ ...form, company: v })}
                 options={['', ...companies.map((c) => c.company_name)]} />
        <Input label="Name *" v={form.name} on={(v) => setForm({ ...form, name: v })} />
        <Input label="Hub" v={form.hub} on={(v) => setForm({ ...form, hub: v })} />
        <SelectF label="Vehicle" v={form.vehicle} on={(v) => setForm({ ...form, vehicle: v })}
                 options={['', 'EV', 'BIKE', 'OTHER']} />
        <Input label="Account #" v={form.account_no} on={(v) => setForm({ ...form, account_no: v })} />
        <Input label="IFSC" v={form.ifsc} on={(v) => setForm({ ...form, ifsc: v.toUpperCase() })} />
        <Input label="Phone" v={form.mob_no} on={(v) => setForm({ ...form, mob_no: v })} />
        <div className="col-span-2 text-xs text-slate-500 -mt-1">
          Leave Rider ID blank to auto-assign a placeholder (QSPEND…).
          Duplicate by name or account at the same company will be refused.
        </div>
        <div className="col-span-2 flex gap-2 items-center mt-1">
          <Submit busy={busy} disabled={!form.company || !form.name} label="Add Rider" />
          {msg && <span className={'text-xs ' + (msgTone === 'err' ? 'text-red-600' : 'text-green-700')}>{msg}</span>}
        </div>
      </form>
    </Card>
  )
}

function BulkUploadCard({ onUploaded }: { onUploaded: () => void }) {
  const [open, setOpen] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState<'preview' | 'commit' | null>(null)
  type Report = {
    committed: boolean
    summary: { would_create: number; duplicates: number; skipped: number; errors: number }
    created: { line: number; rider_id: string; name: string; company: string }[]
    duplicates: { line: number; name: string; company: string; existing_rider_id: string }[]
    skipped: { line: number; reason: string }[]
    errors: string[]
  }
  const [report, setReport] = useState<Report | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function send(commit: boolean) {
    if (!file) return
    setBusy(commit ? 'commit' : 'preview'); setError(null); setReport(null)
    try {
      const form = new FormData()
      form.set('file', file)
      const r = await api.postForm<Report>(`/riders/bulk?commit=${commit}`, form)
      setReport(r)
      if (r.committed) onUploaded()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed')
    } finally {
      setBusy(null)
    }
  }
  return (
    <Card title="Bulk Upload Riders" open={open} onToggle={() => setOpen(!open)}>
      <p className="text-xs text-slate-500 mb-2">
        Excel columns: <code className="bg-slate-100 px-1 rounded">company</code>,
        <code className="bg-slate-100 px-1 rounded">name</code> (required);
        plus <code>rider_id</code>, <code>hub</code>, <code>vehicle</code>,
        <code>account_no</code>, <code>ifsc</code>. Blank rider_id → auto QSPEND placeholder.
      </p>
      <div className="flex gap-2 items-center mb-3 flex-wrap">
        <input type="file" accept=".xlsx,.xls"
               onChange={(e) => setFile(e.target.files?.[0] ?? null)}
               className="text-sm" />
        <button type="button" onClick={() => send(false)}
                disabled={!file || !!busy}
                className="text-sm bg-slate-200 hover:bg-slate-300 px-3 py-1.5 rounded disabled:opacity-50">
          {busy === 'preview' ? 'Previewing…' : 'Preview'}
        </button>
        <button type="button" onClick={() => send(true)}
                disabled={!file || !!busy || !report || report.summary.errors > 0}
                className="text-sm bg-brand hover:bg-brand-700 text-white px-3 py-1.5 rounded disabled:opacity-50">
          {busy === 'commit' ? 'Committing…' : 'Commit'}
        </button>
      </div>
      {error && <p className="text-red-600 text-xs">{error}</p>}
      {report && (
        <div className="text-xs space-y-2">
          <p className={report.committed ? 'text-green-700 font-medium' : 'text-slate-600'}>
            {report.committed ? '✓ Committed' : 'Dry run'} —
            create {report.summary.would_create},
            duplicates {report.summary.duplicates},
            skipped {report.summary.skipped},
            errors {report.summary.errors}
          </p>
          {report.duplicates.length > 0 && (
            <details className="bg-amber-50 border border-amber-200 rounded p-2">
              <summary className="cursor-pointer">Duplicates ({report.duplicates.length})</summary>
              <ul className="mt-1 ml-3 list-disc">
                {report.duplicates.map((d, i) => (
                  <li key={i}>L{d.line}: {d.name} @ {d.company} — already exists as {d.existing_rider_id}</li>
                ))}
              </ul>
            </details>
          )}
          {report.skipped.length > 0 && (
            <details className="bg-slate-50 border border-slate-200 rounded p-2">
              <summary className="cursor-pointer">Skipped ({report.skipped.length})</summary>
              <ul className="mt-1 ml-3 list-disc">
                {report.skipped.map((s, i) => <li key={i}>L{s.line}: {s.reason}</li>)}
              </ul>
            </details>
          )}
          {report.errors.length > 0 && (
            <details className="bg-red-50 border border-red-200 rounded p-2" open>
              <summary className="cursor-pointer">Errors ({report.errors.length}) — fix and re-preview</summary>
              <ul className="mt-1 ml-3 list-disc text-red-700">
                {report.errors.map((e, i) => <li key={i}>{e}</li>)}
              </ul>
            </details>
          )}
        </div>
      )}
    </Card>
  )
}

function BulkUpdateCard({ onUpdated }: { onUpdated: () => void }) {
  const [open, setOpen] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [matchBy, setMatchBy] = useState<'rider_id+company' | 'account_no+company'>('rider_id+company')
  const [busy, setBusy] = useState<'preview' | 'commit' | null>(null)
  type Report = {
    committed: boolean
    match_by: string
    summary: { would_update: number; unchanged: number; not_found: number; errors: number }
    updated: { line: number; rider_id: string; company: string;
               fields: string[]; values: Record<string, string> }[]
    unchanged: { line: number; rider_id: string; company: string }[]
    not_found: { line: number; company: string; key: string | null }[]
    errors: string[]
  }
  const [report, setReport] = useState<Report | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function send(commit: boolean) {
    if (!file) return
    setBusy(commit ? 'commit' : 'preview'); setError(null); setReport(null)
    try {
      const form = new FormData()
      form.set('file', file)
      const r = await api.postForm<Report>(
        `/riders/bulk-update?commit=${commit}&match_by=${encodeURIComponent(matchBy)}`,
        form,
      )
      setReport(r)
      if (r.committed) onUpdated()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed')
    } finally {
      setBusy(null)
    }
  }

  return (
    <Card title="Bulk Update Rider Details" open={open} onToggle={() => setOpen(!open)}>
      <p className="text-xs text-slate-500 mb-2">
        Fill in or correct account numbers, IFSC codes, hub, vehicle, or name
        for many riders at once. Excel or CSV. Match each row by either
        {' '}<code className="bg-slate-100 px-1 rounded">rider_id + company</code> or
        {' '}<code className="bg-slate-100 px-1 rounded">account_no + company</code>.
        Empty cells are ignored (existing value kept).
      </p>
      <div className="flex gap-2 items-center mb-2 flex-wrap">
        <label className="text-xs">
          <span className="block text-[10px] text-slate-500">Match by</span>
          <select value={matchBy}
                  onChange={(e) => setMatchBy(e.target.value as typeof matchBy)}
                  className="border rounded px-2 py-1 text-xs">
            <option value="rider_id+company">rider_id + company</option>
            <option value="account_no+company">account_no + company</option>
          </select>
        </label>
        <input type="file" accept=".xlsx,.xls,.csv,.tsv"
               onChange={(e) => setFile(e.target.files?.[0] ?? null)}
               className="text-sm" />
        <button type="button" onClick={() => send(false)}
                disabled={!file || !!busy}
                className="text-sm bg-slate-200 hover:bg-slate-300 px-3 py-1.5 rounded disabled:opacity-50">
          {busy === 'preview' ? 'Previewing…' : 'Preview'}
        </button>
        <button type="button" onClick={() => send(true)}
                disabled={!file || !!busy || !report || report.summary.errors > 0}
                className="text-sm bg-brand hover:bg-brand-700 text-white px-3 py-1.5 rounded disabled:opacity-50">
          {busy === 'commit' ? 'Committing…' : 'Commit'}
        </button>
      </div>
      {error && <p className="text-red-600 text-xs">{error}</p>}
      {report && (
        <div className="text-xs space-y-2">
          <p className={report.committed ? 'text-green-700 font-medium' : 'text-slate-600'}>
            {report.committed ? '✓ Committed' : 'Dry run'} —
            update {report.summary.would_update},
            unchanged {report.summary.unchanged},
            not found {report.summary.not_found},
            errors {report.summary.errors}
          </p>
          {report.updated.length > 0 && (
            <details className="bg-emerald-50 border border-emerald-200 rounded p-2" open={!report.committed}>
              <summary className="cursor-pointer">Updates ({report.updated.length})</summary>
              <ul className="mt-1 ml-3 list-disc max-h-48 overflow-y-auto">
                {report.updated.slice(0, 200).map((u, i) => (
                  <li key={i}>
                    L{u.line}: <b>{u.rider_id}</b> @ {u.company} — set{' '}
                    {u.fields.map((f) => `${f}=${u.values[f]}`).join(', ')}
                  </li>
                ))}
                {report.updated.length > 200 && (
                  <li className="text-slate-500">…and {report.updated.length - 200} more</li>
                )}
              </ul>
            </details>
          )}
          {report.not_found.length > 0 && (
            <details className="bg-amber-50 border border-amber-200 rounded p-2">
              <summary className="cursor-pointer">Not found ({report.not_found.length})</summary>
              <ul className="mt-1 ml-3 list-disc">
                {report.not_found.map((n, i) => (
                  <li key={i}>L{n.line}: {n.key ?? '?'} @ {n.company}</li>
                ))}
              </ul>
            </details>
          )}
          {report.errors.length > 0 && (
            <details className="bg-red-50 border border-red-200 rounded p-2" open>
              <summary className="cursor-pointer">Errors ({report.errors.length}) — fix and re-preview</summary>
              <ul className="mt-1 ml-3 list-disc text-red-700">
                {report.errors.map((e, i) => <li key={i}>{e}</li>)}
              </ul>
            </details>
          )}
        </div>
      )}
    </Card>
  )
}

function LinkRidersCard({ onLinked }: { onLinked: () => void }) {
  const [open, setOpen] = useState(false)
  const [primary, setPrimary] = useState('')
  const [secondary, setSecondary] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [tone, setTone] = useState<'ok' | 'err'>('ok')

  const pInt = parseInt(primary.trim(), 10)
  const sInt = parseInt(secondary.trim(), 10)
  const valid = Number.isFinite(pInt) && pInt > 0 &&
                Number.isFinite(sInt) && sInt > 0 && pInt !== sInt

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!valid) {
      setTone('err'); setMsg('Enter two different positive Person IDs.'); return
    }
    setBusy(true); setMsg(null)
    try {
      const r = await api.post<{ merged: boolean; into_person_id?: number; reason?: string }>(
        '/persons/link',
        { primary_person_id: pInt, secondary_person_id: sInt },
      )
      setTone(r.merged ? 'ok' : 'err')
      setMsg(r.merged ? `Merged secondary #${sInt} into primary #${r.into_person_id}.` : (r.reason ?? 'No change'))
      if (r.merged) { setPrimary(''); setSecondary(''); onLinked() }
    } catch (err) {
      setTone('err')
      setMsg(err instanceof Error ? err.message : 'Failed')
    }
    finally { setBusy(false) }
  }
  return (
    <Card title="Link Riders (Merge People)" open={open} onToggle={() => setOpen(!open)}>
      <p className="text-xs text-slate-500 mb-2">
        Merge by Person ID — the number shown next to each rider in the table.
        Primary keeps their history and display name; secondary's rider IDs,
        transactions, and arrears collapse in.
      </p>
      <form onSubmit={submit} className="grid grid-cols-2 gap-2">
        <Input label="Primary Person ID" v={primary} on={setPrimary} />
        <Input label="Secondary Person ID" v={secondary} on={setSecondary} />
        <div className="col-span-2 flex gap-2 items-center mt-1">
          <Submit busy={busy} disabled={!valid} label="Merge" />
          {msg && (
            <span className={'text-xs ' + (tone === 'err' ? 'text-red-600' : 'text-green-700')}>
              {msg}
            </span>
          )}
        </div>
      </form>
    </Card>
  )
}

function Card({ title, open, onToggle, children }: { title: string; open: boolean; onToggle: () => void; children: React.ReactNode }) {
  return (
    <div className="bg-white/80 backdrop-blur-xl rounded-xl shadow-card transition-shadow duration-200 hover:shadow-glass p-4">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold">{title}</h3>
        <button onClick={onToggle} className="text-sm text-brand underline">{open ? 'Close' : 'Open'}</button>
      </div>
      {open && <div className="mt-3 text-sm">{children}</div>}
    </div>
  )
}
function Th({ children }: { children: React.ReactNode }) { return <th className="px-3 py-2 font-medium text-xs">{children}</th> }
function Td({ children }: { children: React.ReactNode }) { return <td className="px-3 py-2">{children}</td> }
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
  return <button type="submit" disabled={busy || disabled} className="bg-brand hover:bg-brand-700 text-white px-3 py-1.5 rounded disabled:opacity-50">
    {busy ? '...' : label}</button>
}
