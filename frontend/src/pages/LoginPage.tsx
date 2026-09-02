import { FormEvent, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { useApi } from '../hooks/useApi'

export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // The demo button only makes sense where the server actually seeded the demo
  // accounts (PAYOUT_SEED_DEMO=1). On a real deployment it used to render
  // anyway — advertising an admin password — and fail with "invalid".
  const health = useApi<{ status: string; demo: boolean }>('/health', [], { silent401: true })
  const demo = health.data?.demo === true

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

  const inputCls =
    'w-full rounded-lg bg-white/5 border border-white/10 px-3 py-2.5 text-sm text-white ' +
    'placeholder-silver-500 focus:outline-none focus:ring-2 focus:ring-white/30 ' +
    'focus:border-white/30 transition'

  return (
    <div className="auth-bg min-h-screen flex items-center justify-center p-6">
      <div className="w-full max-w-sm animate-fade-up">
        <div className="flex items-center gap-2.5 mb-6 justify-center">
          <div className="h-10 w-10 rounded-xl grid place-items-center font-display font-bold text-white text-lg
                          bg-gradient-to-br from-brand-400 to-brand-800
                          shadow-[0_0_0_1px_rgba(122,178,242,0.35),0_2px_16px_-2px_rgba(57,135,229,0.7)]">P</div>
          <span className="text-xl font-display font-semibold tracking-tight text-white">Payout System</span>
        </div>
        <form onSubmit={onSubmit}
              className="rounded-2xl bg-white/[0.06] backdrop-blur-2xl border border-white/10 shadow-glow p-8">
          <h1 className="text-xl font-display font-semibold text-white">Sign in</h1>
          <p className="text-silver-400 text-sm mb-6 mt-1">Welcome back. Enter your details.</p>

          <label className="block text-xs font-medium text-silver-300 mb-1">Email</label>
          <input
            type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
            className={inputCls + ' mb-4'} autoComplete="email" placeholder="you@company.com"
          />
          <label className="block text-xs font-medium text-silver-300 mb-1">Password</label>
          <input
            type="password" required value={password} onChange={(e) => setPassword(e.target.value)}
            className={inputCls + ' mb-2'} autoComplete="current-password" placeholder="••••••••"
          />

          <div className="text-right mb-4">
            <Link to="/forgot-password" className="text-xs text-silver-400 hover:text-white transition-colors">
              Forgot password?
            </Link>
          </div>

          {error && <p className="text-rose-300 text-sm mb-3">{error}</p>}

          <button
            type="submit" disabled={busy}
            className="w-full btn-primary justify-center !py-2.5 disabled:opacity-60"
          >
            {busy ? 'Signing in…' : 'Sign in'}
          </button>

          {demo && (
            <>
              <div className="my-4 flex items-center gap-3 text-[11px] text-silver-500">
                <span className="h-px flex-1 bg-white/10" />or<span className="h-px flex-1 bg-white/10" />
              </div>

              <button
                type="button" onClick={() => signIn('admin@demo.com', 'Demo-1234')} disabled={busy}
                className="w-full border border-white/15 text-silver-200 hover:bg-white/5 hover:text-white
                           font-medium py-2.5 rounded-lg text-sm transition-all disabled:opacity-60"
              >
                Explore the live demo
              </button>
              <p className="text-[11px] text-silver-500 text-center mt-2">Sample data · no sign-up required</p>
            </>
          )}
        </form>
      </div>
    </div>
  )
}
