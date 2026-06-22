import { FormEvent, useState } from 'react'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'

export function SettingsPage() {
  const { user } = useAuth()
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

      <div className="bg-white rounded-xl shadow-card p-4 mb-6">
        <h3 className="font-semibold mb-2">Profile</h3>
        <dl className="text-sm grid grid-cols-2 gap-y-1">
          <dt className="text-slate-500">Email</dt><dd>{user?.email}</dd>
          <dt className="text-slate-500">Role</dt><dd>{user?.role}</dd>
        </dl>
      </div>

      <form onSubmit={submit} className="bg-white rounded-xl shadow-card p-4">
        <h3 className="font-semibold mb-3">Change Password</h3>
        <div className="grid gap-3">
          <Field label="Current password" type="password" v={current} on={setCurrent} />
          <Field label="New password" type="password" v={next} on={setNext} />
          <Field label="Confirm new password" type="password" v={confirm} on={setConfirm} />
        </div>
        {error && <p className="text-red-600 text-sm mt-3">{error}</p>}
        {msg && <p className="text-green-700 text-sm mt-3">{msg}</p>}
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
    <input type={type} value={v} onChange={(e) => on(e.target.value)} className="w-full border rounded px-3 py-2" />
  </label>
}
