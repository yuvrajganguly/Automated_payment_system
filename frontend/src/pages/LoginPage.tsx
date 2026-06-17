import { FormEvent, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await login(email, password)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setBusy(false)
    }
  }

  function fillDemo() {
    setEmail('admin@demo.com')
    setPassword('Demo-1234')
    setError(null)
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50">
      <form onSubmit={onSubmit} className="bg-white rounded-lg shadow p-8 w-full max-w-sm">
        <h1 className="text-2xl font-bold mb-1">Payout System</h1>
        <p className="text-slate-500 text-sm mb-6">Sign in to continue</p>

        {/* Demo banner */}
        <div className="mb-5 rounded-md border border-blue-200 bg-blue-50 px-4 py-3 flex items-center justify-between gap-3">
          <div className="text-xs text-blue-700 leading-snug">
            <span className="font-semibold block mb-0.5">Just browsing?</span>
            admin@demo.com · Demo-1234
          </div>
          <button
            type="button"
            onClick={fillDemo}
            className="shrink-0 text-xs font-semibold bg-blue-600 hover:bg-blue-700 text-white px-3 py-1.5 rounded"
          >
            Try Demo
          </button>
        </div>

        <label className="block text-sm font-medium mb-1">Email</label>
        <input
          type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
          className="w-full border rounded px-3 py-2 mb-4 focus:outline-none focus:ring-2 focus:ring-brand"
          autoComplete="email"
        />
        <label className="block text-sm font-medium mb-1">Password</label>
        <input
          type="password" required value={password} onChange={(e) => setPassword(e.target.value)}
          className="w-full border rounded px-3 py-2 mb-4 focus:outline-none focus:ring-2 focus:ring-brand"
          autoComplete="current-password"
        />
        {error && <p className="text-red-600 text-sm mb-3">{error}</p>}
        <button
          type="submit" disabled={busy}
          className="w-full bg-brand hover:bg-brand-700 text-white font-semibold py-2 rounded disabled:opacity-60"
        >
          {busy ? 'Signing in...' : 'Sign in'}
        </button>
        <p className="text-xs text-slate-500 mt-3 text-right">
          <a href="/forgot-password" className="text-brand underline">Forgot password?</a>
        </p>
      </form>
    </div>
  )
}
