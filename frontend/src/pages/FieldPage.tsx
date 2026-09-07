import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { Spinner } from '../components/Spinner'

/**
 * What the field did, and where the field was — deliberately two lists.
 *
 * They answer different questions and come from different places. An activity
 * row is one action (a rider onboarded, an EV handed over) and carries the
 * location the phone stamped on that request, when it had one. The trail is
 * the recruiter's own stream: one fix per app open, at most one every 30
 * minutes, kept whether or not anything was done. Mixing them would suggest
 * the app is following people around between actions; it isn't, and the two
 * lists side by side say so.
 */
interface ActivityRow {
  id: number
  at: string
  email: string
  role: string
  action: string
  action_label: string
  entity_type: string | null
  entity_id: string | null
  entity_label: string | null
  person_id: number | null
  lat: number | null
  lng: number | null
  accuracy_m: number | null
}

interface FixRow {
  id: number
  email: string
  at: string
  lat: number
  lng: number
  accuracy_m: number | null
  area: string | null
  source: string | null
}

interface PersonRow {
  email: string
  role: string
  actions: number
  last_at: string | null
}

const mapUrl = (lat: number, lng: number) => `https://www.google.com/maps?q=${lat},${lng}`

function since(days: number): string {
  const d = new Date(Date.now() - days * 86_400_000)
  return d.toISOString().slice(0, 10)
}

export function FieldPage() {
  const [days, setDays] = useState(1)
  const [who, setWho] = useState<string>('')
  const people = useApi<PersonRow[]>('/activity/people')
  const from = useMemo(() => since(days), [days])

  const field = (people.data ?? []).filter((p) => p.role === 'recruiter')
  const chosen = who || field[0]?.email || ''

  const acts = useApi<ActivityRow[]>(
    chosen ? `/activity?email=${encodeURIComponent(chosen)}&since=${from}&limit=300` : null,
    [chosen, from],
  )
  const fixes = useApi<FixRow[]>(
    chosen ? `/app/locations?email=${encodeURIComponent(chosen)}&since=${from}&limit=300` : null,
    [chosen, from],
  )

  return (
    <div className="max-w-6xl mx-auto">
      <h1 className="page-title mb-1">Field</h1>
      <p className="text-slate-500 text-sm mb-5">
        A recruiter's day from two angles: what they did, and where the app saw them. The app takes one
        fix when it is opened, never in the background, and at most one every 30 minutes.
      </p>

      <div className="flex flex-wrap items-center gap-2 mb-4">
        <select value={chosen} onChange={(e) => setWho(e.target.value)}
                className="border border-slate-300 rounded-lg px-2 py-1 text-sm">
          {field.length === 0 && <option value="">No recruiters yet</option>}
          {field.map((p) => (
            <option key={p.email} value={p.email}>{p.email} · {p.actions} actions</option>
          ))}
        </select>
        <div className="flex items-center gap-1 ml-2">
          {[1, 7, 30].map((d) => (
            <button key={d} onClick={() => setDays(d)}
                    className={'px-3 py-1 rounded-lg text-sm ' + (days === d ? 'bg-brand-500/20 text-white' : 'text-slate-500 hover:text-slate-800')}>
              {d === 1 ? 'Today' : `${d} days`}
            </button>
          ))}
        </div>
      </div>

      {people.loading && <Spinner />}
      {!people.loading && field.length === 0 && (
        <div className="panel p-4 text-sm text-slate-500">
          No recruiter has used the app yet. Create one on the Users page and set their zone.
        </div>
      )}

      {chosen && (
        <div className="grid gap-4 lg:grid-cols-2">
          <section className="panel overflow-hidden">
            <header className="px-4 py-2 border-b border-slate-100 flex items-baseline justify-between">
              <h2 className="font-semibold text-slate-900">Actions</h2>
              <span className="text-xs text-slate-500">{acts.data?.length ?? 0} since {from}</span>
            </header>
            {acts.loading ? <div className="p-6"><Spinner /></div>
              : acts.error ? <div className="p-4 text-sm text-critical">{acts.error}</div>
              : !acts.data?.length ? <div className="p-4 text-sm text-slate-500">Nothing in this window.</div>
              : acts.data.map((a) => (
                <div key={a.id} className="px-4 py-2 border-t border-slate-100 first:border-t-0 text-sm">
                  <div className="flex items-baseline gap-2">
                    <span className="font-medium text-slate-900">{a.action_label}</span>
                    {a.person_id != null && (
                      <Link to={`/persons/${a.person_id}`} className="text-brand-600 hover:underline">
                        {a.entity_label ?? `#${a.person_id}`}
                      </Link>
                    )}
                    {a.person_id == null && a.entity_label && <span className="text-slate-600">{a.entity_label}</span>}
                  </div>
                  <div className="text-xs text-slate-500">
                    {a.at}
                    {a.lat != null && a.lng != null ? (
                      <>
                        {' · '}
                        <a href={mapUrl(a.lat, a.lng)} target="_blank" rel="noreferrer"
                           className="text-brand-600 hover:underline">
                          📍 {a.lat.toFixed(4)}, {a.lng.toFixed(4)}
                        </a>
                        {a.accuracy_m != null && ` ±${Math.round(a.accuracy_m)} m`}
                      </>
                    ) : (
                      <span className="text-slate-400"> · no location</span>
                    )}
                  </div>
                </div>
              ))}
          </section>

          <section className="panel overflow-hidden">
            <header className="px-4 py-2 border-b border-slate-100 flex items-baseline justify-between">
              <h2 className="font-semibold text-slate-900">Location trail</h2>
              <span className="text-xs text-slate-500">{fixes.data?.length ?? 0} fixes</span>
            </header>
            {fixes.loading ? <div className="p-6"><Spinner /></div>
              : fixes.error ? <div className="p-4 text-sm text-critical">{fixes.error}</div>
              : !fixes.data?.length ? (
                <div className="p-4 text-sm text-slate-500">
                  No fixes in this window — the app was not opened, or location is off on that phone.
                </div>
              ) : fixes.data.map((f) => (
                <div key={f.id} className="px-4 py-2 border-t border-slate-100 first:border-t-0 text-sm">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-slate-900">{f.area ?? 'Unnamed spot'}</span>
                    <span className="text-xs text-slate-500">{f.at}</span>
                  </div>
                  <div className="text-xs text-slate-500">
                    <a href={mapUrl(f.lat, f.lng)} target="_blank" rel="noreferrer"
                       className="text-brand-600 hover:underline">
                      {f.lat.toFixed(5)}, {f.lng.toFixed(5)}
                    </a>
                    {f.accuracy_m != null && ` · ±${Math.round(f.accuracy_m)} m`}
                    {f.source && f.source !== 'app_open' && ` · ${f.source}`}
                  </div>
                </div>
              ))}
          </section>
        </div>
      )}
    </div>
  )
}
