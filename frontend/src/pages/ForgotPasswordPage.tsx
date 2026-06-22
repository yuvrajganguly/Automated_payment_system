import { FormEvent, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

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
      const r = await fetch('/api/auth/forgot-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      })
      const j = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(j.detail ?? r.statusText)
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
      const r = await fetch('/api/auth/reset-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, otp, new_password: newPw }),
      })
      const j = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(j.detail ?? r.statusText)
      setStage('done')
      setTimeout(() => navigate('/login'), 1500)
    } catch (e) {
      setMsg({ tone: 'err', text: e instanceof Error ? e.message : 'Failed' })
    } finally { setBusy(false) }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50">
      <div className="bg-white rounded-xl shadow-card p-8 w-full max-w-sm">
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
          <p className="text-green-700 text-sm">Password updated. Redirecting to sign-in…</p>
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
  return <p className={'text-sm mt-3 ' + (tone === 'err' ? 'text-red-600' : 'text-green-700')}>{children}</p>
}
