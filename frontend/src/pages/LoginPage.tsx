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

  async function signIn(em: string, pw: string) {
    setError(null)
    setBusy(true)
    try {
      await login(em, pw)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setBusy(false)
    }
  }

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    signIn(email, password)
  }

  return (
    <div className="min-h-screen flex">
      {/* Brand panel (md+) */}
      <div className="hidden md:flex md:w-1/2 flex-col justify-between p-12
                      bg-gradient-to-br from-brand-700 to-brand-900 text-white">
        <div className="flex items-center gap-2.5">
          <div className="h-9 w-9 rounded-lg bg-white/15 grid place-items-center font-bold">P</div>
          <span className="font-semibold tracking-tight">Payout System</span>
        </div>
        <div>
          <h2 className="text-3xl font-semibold leading-tight tracking-tight">
            Rider payouts, EV rent<br />&amp; reconciliation.
          </h2>
          <p className="mt-4 text-white/70 text-sm max-w-sm leading-relaxed">
            Multi-company pay cycles, handover-prorated EV-rent metering, COD holds,
            and weekly provider reconciliation — in one auditable system.
          </p>
        </div>
        <p className="text-white/40 text-xs">© {new Date().getFullYear()} Payout System</p>
      </div>

      {/* Form */}
      <div className="flex-1 flex items-center justify-center p-6 bg-slate-50">
        <form onSubmit={onSubmit} className="bg-white rounded-2xl shadow-card border border-slate-100 p-8 w-full max-w-sm">
          <div className="md:hidden flex items-center gap-2.5 mb-6">
            <div className="h-9 w-9 rounded-lg bg-brand grid place-items-center text-white font-bold">P</div>
            <span className="font-semibold tracking-tight text-slate-800">Payout System</span>
          </div>

          <h1 className="text-xl font-semibold tracking-tight text-slate-900">Sign in</h1>
          <p className="text-slate-500 text-sm mb-6 mt-1">Welcome back. Enter your details.</p>

          <label className="block text-sm font-medium text-slate-700 mb-1">Email</label>
          <input
            type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
            className="w-full border border-slate-300 rounded-lg px-3 py-2 mb-4 text-sm
                       focus:outline-none focus:ring-2 focus:ring-brand/40 focus:border-brand"
            autoComplete="email" placeholder="you@company.com"
          />
          <label className="block text-sm font-medium text-slate-700 mb-1">Password</label>
          <input
            type="password" required value={password} onChange={(e) => setPassword(e.target.value)}
            className="w-full border border-slate-300 rounded-lg px-3 py-2 mb-2 text-sm
                       focus:outline-none focus:ring-2 focus:ring-brand/40 focus:border-brand"
            autoComplete="current-password" placeholder="••••••••"
          />

          <div className="text-right mb-4">
            <a href="/forgot-password" className="text-xs text-brand hover:underline">Forgot password?</a>
          </div>

          {error && <p className="text-red-600 text-sm mb-3">{error}</p>}

          <button
            type="submit" disabled={busy}
            className="w-full bg-brand hover:bg-brand-700 text-white font-medium py-2.5 rounded-lg
                       text-sm transition-colors disabled:opacity-60"
          >
            {busy ? 'Signing in…' : 'Sign in'}
          </button>

          <div className="my-4 flex items-center gap-3 text-[11px] text-slate-400">
            <span className="h-px flex-1 bg-slate-200" />or<span className="h-px flex-1 bg-slate-200" />
          </div>

          <button
            type="button" onClick={() => signIn('admin@demo.com', 'Demo-1234')} disabled={busy}
            className="w-full border border-slate-300 text-slate-700 hover:bg-slate-50 font-medium
                       py-2.5 rounded-lg text-sm transition-colors disabled:opacity-60"
          >
            Explore the live demo
          </button>
          <p className="text-[11px] text-slate-400 text-center mt-2">
            Sample data · no sign-up required
          </p>
        </form>
      </div>
    </div>
  )
}
