import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { Spinner } from '../components/Spinner'

/** Things that cannot be true.
 *
 * Every data problem this system has had was findable on the day it happened
 * and was found weeks later, because nobody had a page to look at. The rule
 * for what belongs here is in the server's domain/anomalies.py: a finding
 * must be a contradiction, not a judgement. "High arrears" is a report. "Rent
 * charged while the bike was in the workshop" is this page.
 *
 * Empty is the expected state, so the empty state is the design: it has to
 * read as reassurance, not as a page that failed to load.
 */

interface Finding {
  check: string
  severity: 'money' | 'identity' | 'state'
  title: string
  detail: string
  fix: string
  ev_ids?: string[]
  person_ids?: number[]
  amount?: number
}

interface Payload {
  findings: Finding[]
  counts: Partial<Record<Finding['severity'], number>>
  total: number
  checks_run: number
}

const SEVERITY: Record<Finding['severity'], { label: string; chip: string; bar: string }> = {
  money:    { label: 'Money',    chip: 'bg-rose-100 text-rose-800',      bar: 'bg-rose-400' },
  identity: { label: 'Identity', chip: 'bg-amber-100 text-amber-900',    bar: 'bg-amber-400' },
  state:    { label: 'State',    chip: 'bg-slate-200 text-slate-700',    bar: 'bg-slate-300' },
}

const rupees = (paise: number) =>
  '₹' + Math.round(paise / 100).toLocaleString('en-IN')

export function ChecksPage() {
  const [data, setData] = useState<Payload | null>(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    setBusy(true)
    api.get<Payload>('/checks')
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false))
  }
  useEffect(load, [])

  if (busy && !data) return <Spinner />
  if (error) return <div className="p-6 text-rose-700">{error}</div>
  if (!data) return null

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-baseline gap-3 flex-wrap">
        <h1 className="text-xl font-semibold">Checks</h1>
        <span className="text-sm text-slate-500">
          {data.checks_run} checks · {data.total} finding{data.total === 1 ? '' : 's'}
        </span>
        <button
          onClick={load}
          disabled={busy}
          className="ml-auto text-sm px-3 py-1 rounded border border-slate-300
                     hover:bg-slate-50 disabled:opacity-50"
        >
          {busy ? 'Checking…' : 'Run again'}
        </button>
      </div>

      {data.total === 0 ? (
        <div className="rounded border border-emerald-200 bg-emerald-50 p-6 text-emerald-900">
          <div className="font-medium">Nothing to fix.</div>
          <p className="text-sm mt-1 text-emerald-800">
            All {data.checks_run} checks passed. This is the normal state — the page
            is worth opening precisely because it is usually empty.
          </p>
        </div>
      ) : (
        <>
          <div className="flex gap-2 flex-wrap">
            {(Object.keys(SEVERITY) as Finding['severity'][])
              .filter((s) => data.counts[s])
              .map((s) => (
                <span key={s} className={`text-xs px-2 py-1 rounded ${SEVERITY[s].chip}`}>
                  {data.counts[s]} {SEVERITY[s].label.toLowerCase()}
                </span>
              ))}
          </div>

          <ul className="space-y-3">
            {data.findings.map((f, i) => (
              <li
                key={`${f.check}-${i}`}
                className="flex rounded border border-slate-200 bg-white overflow-hidden"
              >
                <div className={`w-1 shrink-0 ${SEVERITY[f.severity].bar}`} />
                <div className="p-3 space-y-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-medium">{f.title}</span>
                    <span className={`text-[11px] px-1.5 py-0.5 rounded ${SEVERITY[f.severity].chip}`}>
                      {SEVERITY[f.severity].label}
                    </span>
                    {f.amount ? (
                      <span className="text-sm text-rose-700">{rupees(f.amount)}</span>
                    ) : null}
                  </div>
                  <div className="text-sm text-slate-800 break-words">{f.detail}</div>
                  <div className="text-sm text-slate-500">{f.fix}</div>
                  {(f.person_ids?.length || f.ev_ids?.length) ? (
                    <div className="flex gap-3 flex-wrap pt-1">
                      {f.person_ids?.map((id) => (
                        <Link key={id} to={`/persons/${id}`} className="text-sm text-sky-700 hover:underline">
                          #{id}
                        </Link>
                      ))}
                      {f.ev_ids?.map((id) => (
                        <Link key={id} to={`/evs/${encodeURIComponent(id)}`} className="text-sm text-sky-700 hover:underline">
                          {id}
                        </Link>
                      ))}
                    </div>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

export default ChecksPage
