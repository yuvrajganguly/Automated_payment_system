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
  zone: string | null
  created_at: string | null
}

/**
 * Who may act on whom.
 *
 * An admin administers the accounts they hand out — recruiters and plain
 * users. Acting on another admin (or a creator, which an admin sees as an
 * admin) is refused by `require_admin_over` with a 403, so the button is
 * disabled rather than offered and then failing. A creator is not fenced.
 */
function blockedReason(viewerIsCreator: boolean, targetRole: UserRow['role']): string | null {
  if (viewerIsCreator) return null
  if (targetRole === 'admin' || targetRole === 'creator') {
    return 'Only the creator can act on another admin’s account.'
  }
  return null
}

export function UsersPage() {
  const { user } = useAuth()
  const isCreator = user?.role === 'creator'
  const isAdmin = isCreator || user?.role === 'admin'
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
          : isAdmin
          ? 'Add recruiters and plain users, and manage their accounts. Changing anyone’s role, and anything to do with another admin’s account, stays with the creator.'
          : 'Everyone with access to the system.'}
      </p>

      {isAdmin && <AddUserCard isCreator={isCreator} onAdded={reload} />}

      {busy && <Spinner />}
      {error && <p className="text-red-400 text-sm mb-3">{error}</p>}

      <div className="panel overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-100 text-left">
            <tr>
              <Th>Email</Th><Th>Phone</Th><Th>Role</Th><Th>Zone</Th><Th>Active</Th><Th>Created</Th>
              {isAdmin && <Th>Actions</Th>}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <UserRowEditor key={r.email} row={r} isCreator={isCreator} isAdmin={isAdmin}
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

function UserRowEditor({ row, isCreator, isAdmin, selfEmail, onChanged }:
  { row: UserRow; isCreator: boolean; isAdmin: boolean; selfEmail: string; onChanged: () => void }) {
  const [busy, setBusy] = useState<'role' | 'active' | 'password' | 'phone' | 'zone' | 'sessions' | null>(null)
  // The zone a recruiter works (North / South): their app opens on those stores,
  // and riders they onboard without a hub take this zone.
  async function setZone(zone: string) {
    setBusy('zone'); setError(null)
    try {
      await api.patch('/users/' + encodeURIComponent(row.email) + '/zone', { zone: zone || null })
      onChanged()
    } catch (e) { setError(e instanceof Error ? e.message : 'Failed') }
    finally { setBusy(null) }
  }
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
  // Two-step rather than a native confirm(): the dialog blocks the tab and
  // cannot show whose account this is, which is the one thing that matters.
  const [sessionsArmed, setSessionsArmed] = useState(false)
  const [sessionsMsg, setSessionsMsg] = useState<string | null>(null)
  async function signOutEverywhere() {
    // The lost-phone button: it kills the app sessions, not the console
    // cookie, so say what actually happened rather than "signed out".
    setSessionsArmed(false)
    setBusy('sessions'); setError(null); setSessionsMsg(null)
    try {
      const res = await api.post<{ sessions_revoked: number }>(
        '/users/' + encodeURIComponent(row.email) + '/sign-out-everywhere',
      )
      setSessionsMsg(
        res.sessions_revoked === 0
          ? 'No app sessions were open.'
          : `${res.sessions_revoked} app session${res.sessions_revoked === 1 ? '' : 's'} ended.`,
      )
    } catch (e) { setError(e instanceof Error ? e.message : 'Failed') }
    finally { setBusy(null) }
  }

  // One reason string, reused as every disabled button's title, so an admin is
  // told why rather than left clicking a dead control.
  const blocked = blockedReason(isCreator, row.role)

  return (
    <tr className="border-t">
      <Td>{row.email}{isSelf && <span className="ml-2 text-xs text-slate-400">(you)</span>}</Td>
      <Td>
        {/* `PATCH /users/{email}/phone` is plain `require_admin` — no rank
            check — so the editor is open on every row, unlike the actions. */}
        {isAdmin ? (
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
        {isAdmin && row.role !== 'user' ? (
          <select value={row.zone ?? ''} onChange={(e) => setZone(e.target.value)} disabled={busy === 'zone'}
                  className="text-xs border rounded px-2 py-0.5" title="Zone this recruiter works">
            <option value="">—</option>
            <option value="North">North</option>
            <option value="South">South</option>
          </select>
        ) : (row.zone ?? '')}
      </Td>
      <Td>
        <span className={'text-xs px-1.5 py-0.5 rounded ' +
          (row.is_active ? 'bg-emerald-500/15' : 'bg-red-500/15')}>
          {row.is_active ? 'yes' : 'no'}
        </span>
      </Td>
      <Td className="text-xs">{row.created_at ?? ''}</Td>
      {isAdmin && (
        <Td>
          <button onClick={toggleActive} disabled={busy === 'active' || isSelf || !!blocked}
                  title={blocked ?? (isSelf ? 'You can’t deactivate yourself.' : undefined)}
                  className="text-xs underline text-brand disabled:opacity-30">
            {row.is_active ? 'Deactivate' : 'Reactivate'}
          </button>
          <button onClick={() => setPwOpen((o) => !o)} disabled={!!blocked} title={blocked ?? undefined}
                  className="text-xs underline text-brand ml-3 disabled:opacity-30">
            Set password
          </button>
          {sessionsArmed ? (
            <span className="ml-3 inline-flex items-center gap-2">
              <button onClick={signOutEverywhere} disabled={busy === 'sessions'}
                      className="text-xs underline text-red-400 disabled:opacity-30">
                {busy === 'sessions' ? '…' : `End every app session for ${row.email}?`}
              </button>
              <button onClick={() => setSessionsArmed(false)}
                      className="text-xs underline text-slate-400">Cancel</button>
            </span>
          ) : (
            <button onClick={() => setSessionsArmed(true)} disabled={!!blocked}
                    title={blocked ?? 'End every app session on their phone (lost handset).'}
                    className="text-xs underline text-brand ml-3 disabled:opacity-30">
              Sign out everywhere
            </button>
          )}
          {sessionsMsg && <div className="text-xs text-emerald-400 mt-1">{sessionsMsg}</div>}
          {pwOpen && !blocked && (
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

function AddUserCard({ isCreator, onAdded }: { isCreator: boolean; onAdded: () => void }) {
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
            {/* An admin who could mint an admin could escalate their own
                privilege by proxy, so the two senior roles are simply not in
                the list for them — the server refuses them anyway. */}
            <select value={form.role}
                    onChange={(e) => setForm({ ...form, role: e.target.value })}
                    className="w-full border rounded px-2 py-1">
              <option value="user">user</option>
              <option value="recruiter">recruiter</option>
              {isCreator && <option value="admin">admin</option>}
              {isCreator && <option value="creator">creator</option>}
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
