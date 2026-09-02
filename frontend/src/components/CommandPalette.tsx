import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { WORKSPACES } from './workspaces'

/** ⌘K — jump anywhere. Pages always; riders and EVs load once per open so
 *  "kunal" or "RAFT14" takes you straight to the profile. */

interface Item {
  key: string
  group: 'Pages' | 'Riders' | 'EVs'
  label: string
  sub?: string
  to: string
}

interface RiderRow {
  person_id: number
  rider_id: string
  company: string
  name: string | null
  hub: string | null
}
interface EvRow {
  ev_id: string
  provider: string
  model: string
  status: string
  current_rider_name: string | null
}

const PAGE_ITEMS: Item[] = WORKSPACES.flatMap((ws) =>
  ws.pages.map((p) => ({
    key: 'page:' + p.to,
    group: 'Pages' as const,
    label: p.label,
    sub: ws.label,
    to: p.to,
  })),
).concat([{ key: 'page:/system', group: 'Pages', label: 'System', sub: 'Creator', to: '/system' }])

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate()
  const [q, setQ] = useState('')
  const [sel, setSel] = useState(0)
  const [riders, setRiders] = useState<RiderRow[] | null>(null)
  const [evs, setEvs] = useState<EvRow[] | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  // Load the searchable universe once per open (kept until close).
  useEffect(() => {
    if (!open) return
    setQ('')
    setSel(0)
    const t = setTimeout(() => inputRef.current?.focus(), 30)
    if (riders === null) api.get<RiderRow[]>('/riders').then(setRiders).catch(() => setRiders([]))
    if (evs === null) api.get<EvRow[]>('/evs').then(setEvs).catch(() => setEvs([]))
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const items = useMemo<Item[]>(() => {
    const needle = q.trim().toLowerCase()
    const pages = PAGE_ITEMS.filter(
      (p) => !needle || (p.label + ' ' + p.sub).toLowerCase().includes(needle),
    ).slice(0, needle ? 5 : 12)
    if (!needle || needle.length < 2) return pages
    const seen = new Set<number>()
    const riderHits: Item[] = (riders ?? [])
      .filter((r) =>
        [r.name, r.rider_id, String(r.person_id), r.hub].some((v) =>
          (v ?? '').toString().toLowerCase().includes(needle),
        ),
      )
      .filter((r) => (seen.has(r.person_id) ? false : (seen.add(r.person_id), true)))
      .slice(0, 6)
      .map((r) => ({
        key: 'rider:' + r.person_id,
        group: 'Riders' as const,
        label: r.name ?? r.rider_id,
        sub: `${r.rider_id} · ${r.company}${r.hub ? ' · ' + r.hub : ''}`,
        to: '/persons/' + r.person_id,
      }))
    const evHits: Item[] = (evs ?? [])
      .filter((e) =>
        [e.ev_id, e.provider, e.model, e.current_rider_name].some((v) =>
          (v ?? '').toString().toLowerCase().includes(needle),
        ),
      )
      .slice(0, 5)
      .map((e) => ({
        key: 'ev:' + e.ev_id,
        group: 'EVs' as const,
        label: e.ev_id,
        sub: `${e.provider} ${e.model} · ${e.status}${e.current_rider_name ? ' · ' + e.current_rider_name : ''}`,
        to: '/evs/' + encodeURIComponent(e.ev_id),
      }))
    return [...pages, ...riderHits, ...evHits]
  }, [q, riders, evs])

  useEffect(() => setSel(0), [q])
  useEffect(() => {
    listRef.current
      ?.querySelector(`[data-idx="${sel}"]`)
      ?.scrollIntoView({ block: 'nearest' })
  }, [sel])

  const go = (item: Item | undefined) => {
    if (!item) return
    onClose()
    navigate(item.to)
  }

  if (!open) return null

  let lastGroup = ''
  return (
    <div
      className="fixed inset-0 z-50 bg-black/60 backdrop-blur-[3px] flex items-start justify-center
                 pt-[14vh] px-4"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
      role="dialog"
      aria-modal="true"
      aria-label="Jump to"
    >
      <div className="panel-pop w-full max-w-xl overflow-hidden animate-scale-in">
        <div className="flex items-center gap-3 px-4 border-b border-edge">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               className="text-slate-500 shrink-0" strokeWidth="2.4" strokeLinecap="round">
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" />
          </svg>
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown') { e.preventDefault(); setSel((s) => Math.min(s + 1, items.length - 1)) }
              else if (e.key === 'ArrowUp') { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)) }
              else if (e.key === 'Enter') { e.preventDefault(); go(items[sel]) }
              else if (e.key === 'Escape') onClose()
            }}
            placeholder="Search pages, riders, EVs…"
            className="flex-1 !bg-transparent !border-0 !shadow-none py-3.5 text-[15px] text-slate-900
                       placeholder:text-slate-400 focus:!ring-0"
          />
          <kbd className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-white/[0.06]
                          border border-edge text-slate-500">
            esc
          </kbd>
        </div>
        <div ref={listRef} className="max-h-[46vh] overflow-y-auto py-1.5">
          {items.length === 0 && (
            <p className="px-4 py-6 text-sm text-slate-500 text-center">
              Nothing matches “{q}”.
            </p>
          )}
          {items.map((item, i) => {
            const header = item.group !== lastGroup ? item.group : null
            lastGroup = item.group
            return (
              <div key={item.key}>
                {header && (
                  <p className="px-4 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-[0.16em]
                                text-slate-400">
                    {header}
                  </p>
                )}
                <button
                  data-idx={i}
                  onMouseEnter={() => setSel(i)}
                  onClick={() => go(item)}
                  className={
                    'w-full flex items-baseline gap-3 px-4 py-2 text-left transition-colors ' +
                    (i === sel ? 'bg-brand-500/15' : '')
                  }
                >
                  <span className={'text-sm ' + (i === sel ? 'text-white' : 'text-slate-800')}>
                    {item.label}
                  </span>
                  {item.sub && <span className="text-xs text-slate-500 truncate">{item.sub}</span>}
                  {i === sel && (
                    <span className="ml-auto text-[10px] text-brand-300 font-mono shrink-0">↵</span>
                  )}
                </button>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
