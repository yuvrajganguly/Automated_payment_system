import { FormEvent, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client'

type Stage = 'request' | 'reset' | 'done'

export function ForgotPasswordPage() {
  const navigate = useNavigate()
  const [stage, setStage] = useState<Stage>('request')
  const [email, setEmail] = useState('')
  const [otp, setOtp] = useState('')
  const [newPw, setNewPw] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ tone: 'ok' | 'err'; text: string } | null>(null)

  async function sendOtp(e: FormEvent) {
    e.preventDefault(); setBusy(true); setMsg(null)
    try {
      const j = await api.post<{ message?: string }>('/auth/forgot-password', { email }, { silent401: true })
      setMsg({ tone: 'ok', text: j.message ?? 'Code sent. Check your inbox.' })
      setStage('reset')
    } catch (e) {
      setMsg({ tone: 'err', text: e instanceof Error ? e.message : 'Failed' })
    } finally { setBusy(false) }
  }

  async function doReset(e: FormEvent) {
    e.preventDefault(); setBusy(true); setMsg(null)
    if (newPw.length < 8) { setMsg({ tone: 'err', text: 'Password must be 8+ characters.' }); setBusy(false); return }
    if (newPw !== confirm) { setMsg({ tone: 'err', text: 'Passwords don\'t match.' }); setBusy(false); return }
    try {
      await api.post('/auth/reset-password', { email, otp, new_password: newPw }, { silent401: true })
      setStage('done')
      setTimeout(() => navigate('/login'), 1500)
    } catch (e) {
      setMsg({ tone: 'err', text: e instanceof Error ? e.message : 'Failed' })
    } finally { setBusy(false) }
  }

  return (
    <div className="auth-bg min-h-screen flex items-center justify-center">
      <div className="panel p-8 w-full max-w-sm">
        <h1 className="text-2xl font-bold mb-1">Payout System</h1>
        <p className="text-slate-500 text-sm mb-6">
          {stage === 'request' ? 'Enter your email and we\'ll send a 6-digit code.'
           : stage === 'reset' ? 'Check your email for the code and set a new password.'
           : 'Password updated.'}
        </p>

        {stage === 'request' && (
          <form onSubmit={sendOtp}>
            <Label>Email</Label>
            <Input type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
                   autoComplete="email" />
            <Submit busy={busy} label="Send code" />
            {msg && <Msg tone={msg.tone}>{msg.text}</Msg>}
          </form>
        )}

        {stage === 'reset' && (
          <form onSubmit={doReset}>
            <Label>6-digit code</Label>
            <Input value={otp} onChange={(e) => setOtp(e.target.value)}
                   inputMode="numeric" maxLength={6} required
                   placeholder="XXXXXX" />
            <Label>New password</Label>
            <Input type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)}
                   autoComplete="new-password" required />
            <Label>Confirm new password</Label>
            <Input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)}
                   autoComplete="new-password" required />
            <Submit busy={busy} label="Set new password" />
            {msg && <Msg tone={msg.tone}>{msg.text}</Msg>}
            <p className="text-xs text-slate-500 mt-3">
              No code in your inbox?{' '}
              <button type="button" onClick={() => { setStage('request'); setMsg(null) }}
                      className="text-brand underline">Send another</button>
            </p>
          </form>
        )}

        {stage === 'done' && (
          <p className="text-emerald-300 text-sm">Password updated. Redirecting to sign-in…</p>
        )}

        <p className="text-xs text-slate-500 mt-6">
          <Link to="/login" className="text-brand underline">← Back to sign-in</Link>
        </p>
      </div>
    </div>
  )
}

function Label({ children }: { children: React.ReactNode }) {
  return <label className="block text-sm font-medium mb-1">{children}</label>
}
function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props}
                className={'w-full border rounded px-3 py-2 mb-4 focus:outline-none focus:ring-2 focus:ring-brand '
                          + (props.className ?? '')} />
}
function Submit({ busy, label }: { busy: boolean; label: string }) {
  return <button type="submit" disabled={busy}
                 className="w-full bg-brand hover:bg-brand-700 text-white font-semibold py-2 rounded disabled:opacity-60">
    {busy ? 'Working…' : label}
  </button>
}
function Msg({ tone, children }: { tone: 'ok' | 'err'; children: React.ReactNode }) {
  return <p className={'text-sm mt-3 ' + (tone === 'err' ? 'text-red-400' : 'text-emerald-300')}>{children}</p>
}
