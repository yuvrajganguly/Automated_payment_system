import { FormEvent, useEffect, useState } from 'react'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Spinner } from '../components/Spinner'
import { PasswordInput } from '../components/PasswordInput'

interface UserRow {
  email: string
  role: 'user' | 'recruiter' | 'admin' | 'creator'
  is_active: boolean
  phone: string | null
  created_at: string | null
}

export function UsersPage() {
  const { user } = useAuth()
  const isCreator = user?.role === 'creator'
  const [rows, setRows] = useState<UserRow[]>([])
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const reload = () => {
    setBusy(true)
    api.get<UserRow[]>('/users')
      .then(setRows)
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false))
  }
  useEffect(reload, [])

  return (
    <div className="max-w-5xl mx-auto">
      <h1 className="text-2xl font-bold mb-1">Users</h1>
      <p className="text-slate-500 text-sm mb-6">
        {isCreator
          ? "You can change roles, deactivate accounts, and add new users. The creator role is locked to you until you promote someone else first."
          : 'Everyone with access to the system.'}
      </p>

      {isCreator && <AddUserCard onAdded={reload} />}

      {busy && <Spinner />}
      {error && <p className="text-red-400 text-sm mb-3">{error}</p>}

      <div className="panel overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-100 text-left">
            <tr>
              <Th>Email</Th><Th>Phone</Th><Th>Role</Th><Th>Active</Th><Th>Created</Th>
              {isCreator && <Th>Actions</Th>}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <UserRowEditor key={r.email} row={r} isCreator={isCreator}
                             selfEmail={user?.email ?? ''} onChanged={reload} />
            ))}
          </tbody>
        </table>
        {rows.length === 0 && !busy &&
          <p className="p-6 text-center text-slate-500 text-sm">No users yet.</p>}
      </div>
    </div>
  )
}

function UserRowEditor({ row, isCreator, selfEmail, onChanged }:
  { row: UserRow; isCreator: boolean; selfEmail: string; onChanged: () => void }) {
  const [busy, setBusy] = useState<'role' | 'active' | 'password' | 'phone' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const isSelf = row.email === selfEmail

  async function setRole(role: string) {
    setBusy('role'); setError(null)
    try {
      await api.patch('/users/' + encodeURIComponent(row.email) + '/role', { role })
      onChanged()
    } catch (e) { setError(e instanceof Error ? e.message : 'Failed') }
    finally { setBusy(null) }
  }
  const [phoneOpen, setPhoneOpen] = useState(false)
  const [phone, setPhone] = useState(row.phone ?? '')
  async function savePhone(e: FormEvent) {
    e.preventDefault(); setBusy('phone'); setError(null)
    try {
      await api.patch('/users/' + encodeURIComponent(row.email) + '/phone', { phone })
      setPhoneOpen(false); onChanged()
    } catch (err) { setError(err instanceof Error ? err.message : 'Failed') }
    finally { setBusy(null) }
  }
  const [pwOpen, setPwOpen] = useState(false)
  const [newPw, setNewPw] = useState('')
  const [pwMsg, setPwMsg] = useState<string | null>(null)
  async function setPassword(e: FormEvent) {
    e.preventDefault(); setBusy('password'); setError(null); setPwMsg(null)
    try {
      await api.patch('/users/' + encodeURIComponent(row.email) + '/password', { new_password: newPw })
      setPwMsg('Password set — tell them the new one.'); setNewPw(''); setPwOpen(false)
    } catch (err) { setError(err instanceof Error ? err.message : 'Failed') }
    finally { setBusy(null) }
  }
  async function toggleActive() {
    setBusy('active'); setError(null)
    try {
      const path = row.is_active ? 'deactivate' : 'reactivate'
      await api.patch('/users/' + encodeURIComponent(row.email) + '/' + path)
      onChanged()
    } catch (e) { setError(e instanceof Error ? e.message : 'Failed') }
    finally { setBusy(null) }
  }

  return (
    <tr className="border-t">
      <Td>{row.email}{isSelf && <span className="ml-2 text-xs text-slate-400">(you)</span>}</Td>
      <Td>
        {isCreator ? (
          phoneOpen ? (
            <form onSubmit={savePhone} className="flex items-center gap-1">
              <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="98765 43210"
                     className="border rounded px-2 py-1 text-xs w-36" inputMode="tel" autoFocus />
              <button type="submit" disabled={busy === 'phone'} className="text-xs btn-primary !py-1">
                {busy === 'phone' ? '…' : 'Save'}
              </button>
              <button type="button" onClick={() => { setPhoneOpen(false); setPhone(row.phone ?? '') }}
                      className="text-xs underline text-slate-400">Cancel</button>
            </form>
          ) : (
            <button onClick={() => setPhoneOpen(true)} className="text-left hover:underline"
                    title="Edit phone number">
              {row.phone ?? <span className="text-slate-400 text-xs">add</span>}
            </button>
          )
        ) : (row.phone ?? '')}
      </Td>
      <Td>
        {isCreator ? (
          <select value={row.role} onChange={(e) => setRole(e.target.value)}
                  disabled={busy === 'role'}
                  className={'text-xs border rounded px-2 py-0.5 ' +
                    (row.role === 'creator' ? 'bg-purple-500/15'
                     : row.role === 'admin' ? 'bg-emerald-500/15'
                     : row.role === 'recruiter' ? 'bg-sky-500/15'
                     :                        'bg-slate-100')}>
            <option value="user">user</option>
            <option value="recruiter">recruiter</option>
            <option value="admin">admin</option>
            <option value="creator">creator</option>
          </select>
        ) : (
          <span className={'text-xs px-1.5 py-0.5 rounded ' +
            (row.role === 'creator' ? 'bg-purple-500/15'
             : row.role === 'admin' ? 'bg-emerald-500/15'
             : row.role === 'recruiter' ? 'bg-sky-500/15'
             :                        'bg-slate-100')}>{row.role}</span>
        )}
      </Td>
      <Td>
        <span className={'text-xs px-1.5 py-0.5 rounded ' +
          (row.is_active ? 'bg-emerald-500/15' : 'bg-red-500/15')}>
          {row.is_active ? 'yes' : 'no'}
        </span>
      </Td>
      <Td className="text-xs">{row.created_at ?? ''}</Td>
      {isCreator && (
        <Td>
          <button onClick={toggleActive} disabled={busy === 'active' || isSelf}
                  className="text-xs underline text-brand disabled:opacity-30">
            {row.is_active ? 'Deactivate' : 'Reactivate'}
          </button>
          <button onClick={() => setPwOpen((o) => !o)}
                  className="text-xs underline text-brand ml-3">
            Set password
          </button>
          {pwOpen && (
            <form onSubmit={setPassword} className="flex items-center gap-2 mt-2">
              <PasswordInput value={newPw} onChange={(e) => setNewPw(e.target.value)}
                             className="border rounded px-2 py-1 text-xs w-44" minLength={8}
                             required autoComplete="new-password" placeholder="min 8 characters" />
              <button type="submit" disabled={busy === 'password' || newPw.length < 8}
                      className="text-xs btn-primary !py-1 disabled:opacity-30">
                {busy === 'password' ? '…' : 'Save'}
              </button>
            </form>
          )}
          {pwMsg && <div className="text-xs text-emerald-400 mt-1">{pwMsg}</div>}
          {error && <div className="text-xs text-red-400 mt-1">{error}</div>}
        </Td>
      )}
    </tr>
  )
}

function AddUserCard({ onAdded }: { onAdded: () => void }) {
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ email: '', password: '', role: 'user', phone: '' })
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [tone, setTone] = useState<'ok' | 'err'>('ok')

  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setMsg(null)
    try {
      await api.post('/users', form)
      setTone('ok'); setMsg('User created.')
      setForm({ email: '', password: '', role: 'user', phone: '' })
      onAdded()
    } catch (e) {
      setTone('err'); setMsg(e instanceof Error ? e.message : 'Failed')
    } finally { setBusy(false) }
  }

  return (
    <div className="panel p-4 mb-4">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-sm">Add user</h3>
        <button onClick={() => setOpen(!open)} className="text-xs text-brand underline">
          {open ? 'Close' : 'Open'}
        </button>
      </div>
      {open && (
        <form onSubmit={submit} className="grid grid-cols-4 gap-2 mt-3 text-sm">
          <label className="block">
            <span className="block text-xs text-slate-600">Email</span>
            <input type="email" value={form.email}
                   onChange={(e) => setForm({ ...form, email: e.target.value })}
                   className="w-full border rounded px-2 py-1" required />
          </label>
          <label className="block">
            <span className="block text-xs text-slate-600">Phone (optional)</span>
            <input type="tel" value={form.phone} placeholder="98765 43210"
                   onChange={(e) => setForm({ ...form, phone: e.target.value })}
                   className="w-full border rounded px-2 py-1" />
          </label>
          <label className="block">
            <span className="block text-xs text-slate-600">Password</span>
            <PasswordInput value={form.password}
                   onChange={(e) => setForm({ ...form, password: e.target.value })}
                   className="w-full border rounded px-2 py-1" required minLength={8} />
          </label>
          <label className="block">
            <span className="block text-xs text-slate-600">Role</span>
            <select value={form.role}
                    onChange={(e) => setForm({ ...form, role: e.target.value })}
                    className="w-full border rounded px-2 py-1">
              <option value="user">user</option>
              <option value="recruiter">recruiter</option>
              <option value="admin">admin</option>
              <option value="creator">creator</option>
            </select>
          </label>
          <div className="col-span-4 flex gap-2 items-center mt-1">
            <button type="submit" disabled={busy || !form.email || !form.password}
                    className="bg-brand hover:bg-brand-700 text-white px-3 py-1.5 rounded disabled:opacity-50">
              {busy ? '…' : 'Add'}
            </button>
            {msg && <span className={'text-xs ' + (tone === 'err' ? 'text-red-400' : 'text-emerald-300')}>{msg}</span>}
          </div>
        </form>
      )}
    </div>
  )
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="px-3 py-2 font-medium text-xs">{children}</th>
}
function Td({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return <td className={'px-3 py-2 ' + className}>{children}</td>
}
