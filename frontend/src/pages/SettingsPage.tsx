import { FormEvent, useState } from 'react'
import { PasswordInput } from '../components/PasswordInput'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'

export function SettingsPage() {
  const { user, refresh } = useAuth()
  const [phone, setPhone] = useState(user?.phone ?? '')
  const [phoneBusy, setPhoneBusy] = useState(false)
  const [phoneMsg, setPhoneMsg] = useState<string | null>(null)
  async function savePhone(e: FormEvent) {
    e.preventDefault(); setPhoneBusy(true); setPhoneMsg(null)
    try {
      const r = await api.patch<{ phone: string | null }>('/auth/me/phone', { phone })
      setPhone(r.phone ?? '')
      setPhoneMsg(r.phone ? `Saved — you can sign in with ${r.phone}.` : 'Phone number removed.')
      await refresh()
    } catch (err) { setPhoneMsg(err instanceof Error ? err.message : 'Failed') }
    finally { setPhoneBusy(false) }
  }
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function submit(e: FormEvent) {
    e.preventDefault(); setMsg(null); setError(null)
    if (next.length < 8) { setError('New password must be at least 8 characters'); return }
    if (next !== confirm) { setError('New passwords do not match'); return }
    setBusy(true)
    try {
      await api.post('/auth/change-password', { current_password: current, new_password: next })
      setMsg('Password updated.')
      setCurrent(''); setNext(''); setConfirm('')
    } catch (err) { setError(err instanceof Error ? err.message : 'Failed') }
    finally { setBusy(false) }
  }

  return (
    <div className="max-w-xl mx-auto">
      <h1 className="text-2xl font-bold mb-1">Settings</h1>
      <p className="text-slate-500 text-sm mb-6">Your account and password.</p>

      <div className="panel p-4 mb-6">
        <h3 className="font-semibold mb-2">Profile</h3>
        <dl className="text-sm grid grid-cols-2 gap-y-1">
          <dt className="text-slate-500">Email</dt><dd>{user?.email}</dd>
          <dt className="text-slate-500">Role</dt><dd>{user?.role}</dd>
        </dl>
        <form onSubmit={savePhone} className="mt-3 flex flex-wrap items-end gap-2">
          <label className="block flex-1 min-w-[180px]">
            <span className="block text-sm font-medium mb-1">Phone number</span>
            <input value={phone} onChange={(e) => setPhone(e.target.value)} type="tel"
                   placeholder="98765 43210" className="w-full border rounded px-3 py-2" />
          </label>
          <button type="submit" disabled={phoneBusy}
                  className="bg-brand hover:bg-brand-700 text-white px-4 py-2 rounded disabled:opacity-50">
            {phoneBusy ? '…' : 'Save'}
          </button>
          <p className="w-full text-xs text-slate-500">
            Optional. Lets you sign in with the number instead of your email. Leave blank to remove.
            {phoneMsg && <span className="ml-2 text-emerald-300">{phoneMsg}</span>}
          </p>
        </form>
      </div>

      <form onSubmit={submit} className="panel p-4">
        <h3 className="font-semibold mb-3">Change Password</h3>
        <div className="grid gap-3">
          <Field label="Current password" type="password" v={current} on={setCurrent} />
          <Field label="New password" type="password" v={next} on={setNext} />
          <Field label="Confirm new password" type="password" v={confirm} on={setConfirm} />
        </div>
        {error && <p className="text-red-400 text-sm mt-3">{error}</p>}
        {msg && <p className="text-emerald-300 text-sm mt-3">{msg}</p>}
        <button type="submit" disabled={busy || !current || !next || !confirm}
                className="mt-4 bg-brand hover:bg-brand-700 text-white px-4 py-2 rounded disabled:opacity-50">
          {busy ? 'Updating…' : 'Update Password'}
        </button>
      </form>
    </div>
  )
}

function Field({ label, type = 'text', v, on }: { label: string; type?: string; v: string; on: (v: string) => void }) {
  return <label className="block">
    <span className="block text-sm font-medium mb-1">{label}</span>
    {type === 'password'
      ? <PasswordInput value={v} onChange={(e) => on(e.target.value)} className="w-full border rounded px-3 py-2" />
      : <input type={type} value={v} onChange={(e) => on(e.target.value)} className="w-full border rounded px-3 py-2" />}
  </label>
}
