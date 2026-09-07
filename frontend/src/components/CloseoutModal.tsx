import { FormEvent, useEffect, useState } from 'react'
import { api } from '../api/client'
import { rupees } from '../lib/format'

/**
 * EV close-out — what happened to the rider's security deposit when their EV
 * came back. Shown right after a return / mark-spare with a holder, and again
 * from the "waiting" list on the EVs page until every closed unit has an
 * answer. The maths is the server's (POST /evs/closeouts/{assignment_id});
 * this only previews it.
 */
export interface CloseoutPrompt {
  assignment_id: number
  ev_id: string
  person_id: number
  name: string
  model?: string | null
  handover_date?: string | null
  returned_date?: string | null
  arrears_outstanding: number
  dues_outstanding: number
  suggested: { sd_amount: number; rent_charges: number; damage_charges: number }
}

export interface CloseoutResult {
  assignment_id: number
  ev_id: string
  sd_returned: boolean
  sd_amount: number
  damage_charges: number
  rent_charges: number
  rent_applied: number
  refund_due: number
  refund_mode: 'next_payout' | 'cash' | null
  shortfall: number
}

export function closeoutNote(r: CloseoutResult): string {
  const bits: string[] = []
  if (r.sd_returned) {
    bits.push('deposit returned to the rider')
    if (r.shortfall > 0) bits.push(rupees(r.shortfall) + ' damage added to dues')
  } else {
    if (r.rent_applied > 0) bits.push(rupees(r.rent_applied) + ' rent cleared from the deposit')
    if (r.damage_charges > 0) bits.push(rupees(r.damage_charges) + ' damage covered')
    if (r.refund_due > 0) bits.push(rupees(r.refund_due) + (r.refund_mode === 'next_payout' ? ' goes out with the next payout' : ' refunded in cash'))
    if (r.shortfall > 0) bits.push(rupees(r.shortfall) + ' beyond the deposit added to dues')
  }
  return bits.length ? bits.join(' · ') : 'nothing owed either way'
}

export function CloseoutModal({ prompt, onDone, onClose }:
  { prompt: CloseoutPrompt; onDone: (r: CloseoutResult) => void; onClose: () => void }) {
  const [sdReturned, setSdReturned] = useState<boolean | null>(null)
  const [sd, setSd] = useState(String(prompt.suggested.sd_amount))
  const [damage, setDamage] = useState('0')
  const [rent, setRent] = useState(String(prompt.suggested.rent_charges))
  const [credit, setCredit] = useState(true)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setSdReturned(null); setSd(String(prompt.suggested.sd_amount)); setDamage('0')
    setRent(String(prompt.suggested.rent_charges)); setCredit(true); setNote(''); setError(null)
  }, [prompt.assignment_id]) // eslint-disable-line react-hooks/exhaustive-deps

  const n = (s: string) => Math.max(0, Number(s.replace(/[^\d.]/g, '')) || 0)
  const owed = prompt.arrears_outstanding + prompt.dues_outstanding
  // Preview of the server's arithmetic: rent comes off first (never more than what is owed), then damage.
  const rentApplied = Math.min(n(sd), n(rent), owed)
  const left = n(sd) - rentApplied - n(damage)

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (sdReturned === null) { setError('Say whether the deposit was returned.'); return }
    setBusy(true); setError(null)
    try {
      const body = sdReturned
        ? { sd_returned: true, damage_charges: n(damage), note: note || undefined }
        : { sd_returned: false, sd_amount: n(sd), damage_charges: n(damage), rent_charges: n(rent),
            credit_next_payout: credit, note: note || undefined }
      const r = await api.post<CloseoutResult>(`/evs/closeouts/${prompt.assignment_id}`, body)
      onDone(r)
    } catch (err) { setError(err instanceof Error ? err.message : 'Failed') }
    finally { setBusy(false) }
  }

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-[2px] flex items-center justify-center p-4 z-50">
      <form onSubmit={submit} className="panel-pop w-full max-w-lg max-h-[90vh] flex flex-col">
        <div className="px-5 py-3 border-b flex items-center justify-between">
          <div>
            <h3 className="font-semibold">Close out {prompt.ev_id} · {prompt.name}</h3>
            <p className="text-xs text-slate-500">
              The EV is back{prompt.returned_date ? ' as of ' + prompt.returned_date : ''}. What happened to the security deposit?
              {owed > 0 && <> The books show <b>{rupees(owed)}</b> owed
                ({rupees(prompt.arrears_outstanding)} EV rent, {rupees(prompt.dues_outstanding)} dues).</>}
            </p>
          </div>
          <button type="button" onClick={onClose} className="text-slate-500 hover:text-slate-700" title="Later">✕</button>
        </div>
        <div className="px-5 py-4 overflow-y-auto space-y-4 text-sm">
          <div>
            <div className="text-xs font-medium text-slate-500 mb-1">SD returned to the rider?</div>
            <div className="flex gap-2">
              {[['Yes', true], ['No', false]].map(([label, v]) => (
                <button key={String(v)} type="button" onClick={() => setSdReturned(v as boolean)}
                  className={'px-4 py-1.5 rounded border ' + (sdReturned === v ? 'bg-brand text-white border-brand' : 'hover:bg-slate-100')}>
                  {label as string}
                </button>
              ))}
            </div>
          </div>

          {sdReturned === true && (
            <div className="space-y-2">
              <p className="text-xs text-slate-500">The deposit went back in cash. Anything the rider still owes stays as dues; add damage below if any.</p>
              <Field label="Damage charges (₹)" v={damage} on={setDamage} />
            </div>
          )}

          {sdReturned === false && (
            <div className="space-y-2">
              <div className="grid grid-cols-3 gap-2">
                <Field label="SD amount (₹)" v={sd} on={setSd} />
                <Field label="Damage charges (₹)" v={damage} on={setDamage} />
                <Field label="Rent charges (₹)" v={rent} on={setRent} hint={owed > 0 ? `${rupees(owed)} on the books` : 'nothing on the books'} />
              </div>
              <div className="rounded border bg-slate-50 px-3 py-2 text-xs space-y-0.5">
                <div>Rent cleared from the deposit: <b>{rupees(rentApplied)}</b>{n(rent) > owed && <span className="text-slate-500"> (only what the books show as owed)</span>}</div>
                <div>Damage covered: <b>{rupees(Math.min(n(damage), Math.max(0, n(sd) - rentApplied)))}</b></div>
                {left > 0 && <div className="text-emerald-700">Left for the rider: <b>{rupees(left)}</b></div>}
                {left < 0 && <div className="text-red-600">Beyond the deposit — added to dues: <b>{rupees(-left)}</b></div>}
                {left === 0 && <div>Nothing left over.</div>}
              </div>
              {left > 0 && (
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={credit} onChange={(e) => setCredit(e.target.checked)} />
                  Add {rupees(left)} to the rider's next payout processed
                  <span className="text-xs text-slate-500">(unticked = refunded in cash, recorded only)</span>
                </label>
              )}
            </div>
          )}

          {sdReturned !== null && (
            <label className="block">
              <span className="text-xs font-medium text-slate-500">Note (optional)</span>
              <input value={note} onChange={(e) => setNote(e.target.value)} className="w-full border rounded px-2 py-1 mt-0.5" placeholder="e.g. mirror broken, paid at Salt Lake" />
            </label>
          )}
          {error && <p className="text-red-500 text-xs">{error}</p>}
        </div>
        <div className="px-5 py-3 border-t flex justify-end gap-2">
          <button type="button" onClick={onClose} className="px-3 py-1.5 rounded border hover:bg-slate-100">Later</button>
          <button type="submit" disabled={busy || sdReturned === null}
            className="bg-brand hover:bg-brand-700 text-white px-4 py-1.5 rounded disabled:opacity-50">
            {busy ? '…' : 'Record close-out'}
          </button>
        </div>
      </form>
    </div>
  )
}

function Field({ label, v, on, hint }: { label: string; v: string; on: (v: string) => void; hint?: string }) {
  return (
    <label className="block">
      <span className="text-xs font-medium text-slate-500">{label}</span>
      <input value={v} onChange={(e) => on(e.target.value)} inputMode="decimal"
             className="w-full border rounded px-2 py-1 mt-0.5" />
      {hint && <span className="text-[11px] text-slate-400">{hint}</span>}
    </label>
  )
}

/** The "closed, deposit not settled" list — admins clear it from the EVs page. */
export function PendingCloseouts({ onPick, refreshKey }: { onPick: (p: CloseoutPrompt) => void; refreshKey: number }) {
  const [rows, setRows] = useState<CloseoutPrompt[]>([])
  useEffect(() => {
    api.get<CloseoutPrompt[]>('/evs/closeouts?pending=true').then(setRows).catch(() => setRows([]))
  }, [refreshKey])
  if (rows.length === 0) return null
  return (
    <div className="mb-4 rounded border border-amber-300 bg-amber-50 px-4 py-3">
      <div className="flex items-center justify-between">
        <div className="font-medium text-amber-900">{rows.length} EV{rows.length > 1 ? 's' : ''} closed, deposit not settled</div>
        <span className="text-xs text-amber-800">Say whether the SD went back, and what it covered.</span>
      </div>
      <ul className="mt-2 divide-y divide-amber-200 text-sm">
        {rows.map((p) => (
          <li key={p.assignment_id} className="py-1.5 flex items-center gap-3">
            <span className="font-mono">{p.ev_id}</span>
            <span className="flex-1">{p.name}{p.returned_date && <span className="text-slate-500"> · back {p.returned_date}</span>}
              {(p.arrears_outstanding + p.dues_outstanding) > 0 &&
                <span className="text-slate-600"> · owes {rupees(p.arrears_outstanding + p.dues_outstanding)}</span>}
            </span>
            <button onClick={() => onPick(p)} className="text-brand underline text-xs">Close out</button>
          </li>
        ))}
      </ul>
    </div>
  )
}
