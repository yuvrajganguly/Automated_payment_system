import { FormEvent, useState } from 'react'
import emblem from '../assets/qwikserve-emblem.png'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { useApi } from '../hooks/useApi'
import { api } from '../api/client'
import { PasswordInput } from '../components/PasswordInput'

export function LoginPage() {
  const { login, loginWithOtp } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // Passwordless: a WhatsApp code to the phone on the account.
  const [mode, setMode] = useState<'password' | 'otp'>('password')
  const [phone, setPhone] = useState('')
  const [otp, setOtp] = useState('')
  const [codeSent, setCodeSent] = useState(false)
  const [info, setInfo] = useState<string | null>(null)
  // The demo button only makes sense where the server actually seeded the demo
  // accounts (PAYOUT_SEED_DEMO=1). On a real deployment it used to render
  // anyway — advertising an admin password — and fail with "invalid".
  const health = useApi<{ status: string; demo: boolean; whatsapp?: boolean }>('/health', [], { silent401: true })
  const demo = health.data?.demo === true
  const whatsapp = health.data?.whatsapp === true

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
  async function sendCode() {
    setError(null); setInfo(null); setBusy(true)
    try {
      const r = await api.post<{ message: string }>('/auth/otp/send', { phone }, { silent401: true })
      setCodeSent(true); setInfo(r.message)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not send the code')
    } finally { setBusy(false) }
  }
  async function signInWithCode() {
    setError(null); setBusy(true)
    try {
      await loginWithOtp(phone, otp)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-in failed')
    } finally { setBusy(false) }
  }
  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (mode === 'otp') { codeSent ? signInWithCode() : sendCode(); return }
    signIn(email, password)
  }
  const switchMode = (m: 'password' | 'otp') => {
    setMode(m); setError(null); setInfo(null); setCodeSent(false); setOtp('')
  }

  const inputCls =
    'w-full rounded-lg bg-white/5 border border-white/10 px-3 py-2.5 text-sm text-white ' +
    'placeholder-silver-500 focus:outline-none focus:ring-2 focus:ring-white/30 ' +
    'focus:border-white/30 transition'

  return (
    <div className="auth-bg min-h-screen flex items-center justify-center p-6">
      <div className="w-full max-w-sm animate-fade-up">
        <div className="flex flex-col items-center gap-3 mb-6">
          <img src={emblem} alt="QwikServe"
               className="h-16 w-auto drop-shadow-[0_0_24px_rgba(220,38,38,0.5)]" />
          <span className="text-xl font-display font-semibold tracking-tight text-white">
            QwikServe <span className="text-slate-500 font-normal">Payout</span>
          </span>
        </div>
        <form onSubmit={onSubmit}
              className="rounded-2xl bg-white/[0.06] backdrop-blur-2xl border border-white/10 shadow-glow p-8">
          <h1 className="text-xl font-display font-semibold text-white">Sign in</h1>
          <p className="text-silver-400 text-sm mb-6 mt-1">
            {mode === 'otp' ? 'We\'ll send a 6-digit code to your WhatsApp.' : 'Welcome back. Enter your details.'}
          </p>

          {mode === 'password' ? (
            <>
              <label className="block text-xs font-medium text-silver-300 mb-1">Email or phone number</label>
              <input
                type="text" required value={email} onChange={(e) => setEmail(e.target.value)}
                className={inputCls + ' mb-4'} autoComplete="username" placeholder="you@company.com or 98765 43210"
                inputMode="email"
              />
              <label className="block text-xs font-medium text-silver-300 mb-1">Password</label>
              <PasswordInput
                required value={password} onChange={(e) => setPassword(e.target.value)}
                className={inputCls + ' mb-2'} autoComplete="current-password" placeholder="••••••••"
              />

              <div className="text-right mb-4">
                <Link to="/forgot-password" className="text-xs text-silver-400 hover:text-white transition-colors">
                  Forgot password?
                </Link>
              </div>
            </>
          ) : (
            <>
              <label className="block text-xs font-medium text-silver-300 mb-1">Phone number</label>
              <input
                type="tel" required value={phone} onChange={(e) => setPhone(e.target.value)}
                className={inputCls + ' mb-4'} autoComplete="tel" placeholder="98765 43210"
                inputMode="tel" disabled={codeSent}
              />
              {codeSent && (
                <>
                  <label className="block text-xs font-medium text-silver-300 mb-1">Code from WhatsApp</label>
                  <input
                    type="text" required value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))}
                    className={inputCls + ' mb-2 tracking-[0.4em] font-mono'} inputMode="numeric" autoComplete="one-time-code"
                    placeholder="••••••" autoFocus
                  />
                  <div className="text-right mb-4">
                    <button type="button" onClick={() => { setCodeSent(false); setOtp(''); setInfo(null) }}
                            className="text-xs text-silver-400 hover:text-white transition-colors">
                      Wrong number? Send again
                    </button>
                  </div>
                </>
              )}
            </>
          )}

          {info && <p className="text-emerald-300 text-sm mb-3">{info}</p>}
          {error && <p className="text-rose-300 text-sm mb-3">{error}</p>}

          <button
            type="submit" disabled={busy || (mode === 'otp' && codeSent && otp.length < 6)}
            className="w-full btn-primary justify-center !py-2.5 disabled:opacity-60"
          >
            {busy ? (mode === 'otp' && !codeSent ? 'Sending…' : 'Signing in…')
              : mode === 'otp' ? (codeSent ? 'Sign in' : 'Send code on WhatsApp') : 'Sign in'}
          </button>

          {whatsapp && (
            <button
              type="button"
              onClick={() => switchMode(mode === 'otp' ? 'password' : 'otp')}
              className="w-full mt-3 text-xs text-silver-400 hover:text-white transition-colors"
            >
              {mode === 'otp' ? 'Use email and password instead' : 'Sign in with a WhatsApp code instead'}
            </button>
          )}

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
