import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { Spinner } from '../components/Spinner'

const fmt = (n: number) =>
  n.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })
const fmt2 = (n: number) =>
  n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })

interface Summary {
  kpis: {
    active_riders: number
    active_evs: number
    gen_dues: number
    ev_arrears: number
    cod_pending: number
    released_to_date: number
  }
  cycles: {
    company: string
    cycle_start: string
    cycle_end: string
    released: number
    rent_collected: number
    rent_charged: number
    rent_missed: number
    cod_held: number
  }[]
  ev_status: Record<string, number>
  top_owing: {
    person_id: number
    display_name: string
    dues: number
    ev_arrears: number
    cod: number
    total: number
  }[]
  recovery_trend: { cycle_end: string; recovered: number }[]
}

const COMPANY_COLORS: Record<string, string> = {
  Spencer: '#0ea5e9', "Spencer's": '#0ea5e9',
  Myntra:  '#f59e0b',
  Blitz:   '#ef4444',
  Dealshare: '#10b981',
  Jiffy:   '#8b5cf6',
}
const colorFor = (co: string) => COMPANY_COLORS[co] ?? '#64748b'

export function DashboardPage() {
  const [data, setData] = useState<Summary | null>(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.get<Summary>('/dashboard/summary')
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false))
  }, [])

  if (busy && !data) return <Spinner label="Loading dashboard…" />
  if (error || !data) return <p className="text-red-600">{error ?? 'Failed to load'}</p>

  return (
    <div className="max-w-7xl mx-auto">
      <h1 className="text-2xl font-bold mb-1">Dashboard</h1>
      <p className="text-slate-500 text-sm mb-6">
        Everything live: KPIs from the ledger, the last 40 cycle rows, fleet status,
        top owing riders, and EV-rent recovery trend.
      </p>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 mb-6">
        <Kpi label="Active riders" value={fmt(data.kpis.active_riders)} tone="emerald" />
        <Kpi label="Active EVs" value={fmt(data.kpis.active_evs)} tone="sky" />
        <Kpi label="Released to date" value={'₹' + fmt(data.kpis.released_to_date)} tone="slate" big />
        <Kpi label="Dues outstanding" value={'₹' + fmt(data.kpis.gen_dues)} tone="amber" />
        <Kpi label="EV-rent arrears" value={'₹' + fmt(data.kpis.ev_arrears)} tone="red" />
        <Kpi label="COD pending" value={'₹' + fmt(data.kpis.cod_pending)} tone="red" />
      </div>

      <div className="grid lg:grid-cols-2 gap-4 mb-6">
        <Panel title="Released per cycle">
          <CycleLineChart cycles={data.cycles} />
        </Panel>
        <Panel title="Fleet status">
          <FleetDonut status={data.ev_status} />
        </Panel>
      </div>

      <div className="grid lg:grid-cols-2 gap-4 mb-6">
        <Panel title="Top owing riders">
          <TopOwingTable rows={data.top_owing} />
        </Panel>
        <Panel title="EV-rent recovered per cycle">
          <RecoveryTrend rows={data.recovery_trend} />
        </Panel>
      </div>

      <Panel title="Recent cycles">
        <RecentCyclesTable rows={data.cycles} />
      </Panel>
    </div>
  )
}

function Kpi({ label, value, tone, big }:
  { label: string; value: string; tone: 'emerald' | 'sky' | 'slate' | 'amber' | 'red'
    big?: boolean }) {
  const ring = {
    emerald: 'border-emerald-400',
    sky:     'border-sky-400',
    slate:   'border-slate-400',
    amber:   'border-amber-400',
    red:     'border-red-400',
  }[tone]
  return <div className={'bg-white rounded-lg shadow p-3 border-l-4 ' + ring + (big ? ' lg:col-span-2' : '')}>
    <p className="text-xs text-slate-500">{label}</p>
    <p className={'font-bold ' + (big ? 'text-2xl' : 'text-lg')}>{value}</p>
  </div>
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="bg-white rounded-lg shadow p-4 overflow-x-auto">
    <h2 className="font-semibold mb-3 text-sm">{title}</h2>
    {children}
  </section>
}

// ── Line chart: one series per company, x = cycle_end ─────────────────────
function CycleLineChart({ cycles }: { cycles: Summary['cycles'] }) {
  const byCo = useMemo(() => {
    const m = new Map<string, { x: string; y: number }[]>()
    // Sort oldest first so the polyline reads left-to-right
    const sorted = [...cycles].sort(
      (a, b) => a.cycle_end.localeCompare(b.cycle_end)
    )
    for (const c of sorted) {
      const arr = m.get(c.company) ?? []
      arr.push({ x: c.cycle_end, y: c.released })
      m.set(c.company, arr)
    }
    return m
  }, [cycles])

  const allX = useMemo(() => Array.from(new Set(cycles.map((c) => c.cycle_end))).sort(), [cycles])
  const maxY = useMemo(
    () => Math.max(1, ...cycles.map((c) => c.released)),
    [cycles],
  )

  if (cycles.length === 0)
    return <p className="text-slate-500 text-sm p-4">No cycles processed yet.</p>

  const W = 640, H = 200, P = 32
  const xPos = (x: string) => {
    if (allX.length <= 1) return P
    return P + ((W - 2 * P) * allX.indexOf(x)) / (allX.length - 1)
  }
  const yPos = (y: number) => H - P - ((H - 2 * P) * y) / maxY

  return <div>
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ maxHeight: 220 }}>
      {/* y-axis ticks */}
      {[0, 0.25, 0.5, 0.75, 1].map((f, i) => (
        <g key={i}>
          <line x1={P} x2={W - P} y1={H - P - (H - 2 * P) * f}
                y2={H - P - (H - 2 * P) * f} stroke="#e2e8f0" />
          <text x={P - 6} y={H - P - (H - 2 * P) * f + 3} fontSize="9"
                fill="#64748b" textAnchor="end">
            ₹{fmt(maxY * f)}
          </text>
        </g>
      ))}
      {/* polylines */}
      {Array.from(byCo.entries()).map(([co, pts]) => (
        <g key={co}>
          <polyline fill="none" stroke={colorFor(co)} strokeWidth="2"
                    points={pts.map((p) => `${xPos(p.x)},${yPos(p.y)}`).join(' ')} />
          {pts.map((p, i) => (
            <circle key={i} cx={xPos(p.x)} cy={yPos(p.y)} r="2.5" fill={colorFor(co)} />
          ))}
        </g>
      ))}
      {/* x-axis labels: every 2nd point to avoid overlap */}
      {allX.map((x, i) => (i % 2 === 0 || allX.length <= 6) && (
        <text key={x} x={xPos(x)} y={H - 10} fontSize="9" fill="#64748b" textAnchor="middle">
          {x.slice(5)}
        </text>
      ))}
    </svg>
    <div className="flex flex-wrap gap-3 mt-2 text-xs">
      {Array.from(byCo.keys()).map((co) => (
        <span key={co} className="inline-flex items-center gap-1">
          <span className="w-3 h-3 rounded-sm inline-block"
                style={{ background: colorFor(co) }} />
          {co}
        </span>
      ))}
    </div>
  </div>
}

// ── Donut: EV status distribution ─────────────────────────────────────────
function FleetDonut({ status }: { status: Record<string, number> }) {
  const items = useMemo(() => {
    const order = ['in_use', 'spare', 'maintenance', 'returned']
    const colors: Record<string, string> = {
      in_use: '#10b981', spare: '#f59e0b',
      maintenance: '#f97316', returned: '#64748b',
    }
    return order
      .filter((k) => (status[k] ?? 0) > 0)
      .map((k) => ({ label: k, value: status[k], color: colors[k] }))
  }, [status])
  const total = items.reduce((a, i) => a + i.value, 0)
  if (total === 0) return <p className="text-slate-500 text-sm p-4">No EVs yet.</p>

  const R = 70, T = 22
  let acc = 0
  const arcs = items.map((it) => {
    const start = acc / total
    acc += it.value
    const end = acc / total
    return { ...it, start, end }
  })
  const arcPath = (start: number, end: number) => {
    const a0 = 2 * Math.PI * start - Math.PI / 2
    const a1 = 2 * Math.PI * end - Math.PI / 2
    const cx = 100, cy = 100
    const big = end - start > 0.5 ? 1 : 0
    const x0 = cx + R * Math.cos(a0), y0 = cy + R * Math.sin(a0)
    const x1 = cx + R * Math.cos(a1), y1 = cy + R * Math.sin(a1)
    const x2 = cx + (R - T) * Math.cos(a1), y2 = cy + (R - T) * Math.sin(a1)
    const x3 = cx + (R - T) * Math.cos(a0), y3 = cy + (R - T) * Math.sin(a0)
    return `M ${x0} ${y0} A ${R} ${R} 0 ${big} 1 ${x1} ${y1} ` +
           `L ${x2} ${y2} A ${R - T} ${R - T} 0 ${big} 0 ${x3} ${y3} Z`
  }

  return <div className="flex items-center gap-4 flex-wrap">
    <svg viewBox="0 0 200 200" style={{ maxHeight: 200, width: 200 }}>
      {arcs.map((a) => (
        <path key={a.label} d={arcPath(a.start, a.end)} fill={a.color}
              stroke="#fff" strokeWidth="1" />
      ))}
      <text x="100" y="100" textAnchor="middle" dy="-4" fontSize="11" fill="#64748b">
        Total
      </text>
      <text x="100" y="100" textAnchor="middle" dy="14" fontSize="20" fontWeight="700">
        {fmt(total)}
      </text>
    </svg>
    <div className="text-xs space-y-1">
      {items.map((i) => (
        <div key={i.label} className="flex items-center gap-2">
          <span className="w-3 h-3 rounded-sm inline-block" style={{ background: i.color }} />
          <span className="w-20 capitalize text-slate-700">{i.label.replace('_', ' ')}</span>
          <span className="font-medium">{fmt(i.value)}</span>
          <span className="text-slate-400">({((i.value / total) * 100).toFixed(0)}%)</span>
        </div>
      ))}
    </div>
  </div>
}

function TopOwingTable({ rows }: { rows: Summary['top_owing'] }) {
  if (rows.length === 0)
    return <p className="text-slate-500 text-sm p-4">No outstanding balances anywhere. Tidy.</p>
  const max = Math.max(...rows.map((r) => r.total), 1)
  return <table className="w-full text-sm">
    <thead className="bg-slate-50 text-left text-xs">
      <tr><th className="px-2 py-1">Rider</th>
          <th className="px-2 py-1 text-right">Dues</th>
          <th className="px-2 py-1 text-right">EV arrears</th>
          <th className="px-2 py-1 text-right">COD</th>
          <th className="px-2 py-1">Total</th></tr>
    </thead>
    <tbody>
      {rows.map((r) => (
        <tr key={r.person_id} className="border-t">
          <td className="px-2 py-1">
            <Link to={'/persons/' + r.person_id} className="text-brand underline">
              {r.display_name}
            </Link>
          </td>
          <td className="px-2 py-1 text-right">{fmt2(r.dues)}</td>
          <td className="px-2 py-1 text-right">{fmt2(r.ev_arrears)}</td>
          <td className="px-2 py-1 text-right">{fmt2(r.cod)}</td>
          <td className="px-2 py-1">
            <div className="relative h-4 bg-slate-100 rounded">
              <div className="absolute inset-y-0 left-0 bg-red-400 rounded"
                   style={{ width: `${(r.total / max) * 100}%` }} />
              <span className="absolute inset-0 flex items-center justify-end pr-1 text-xs font-medium">
                {fmt2(r.total)}
              </span>
            </div>
          </td>
        </tr>
      ))}
    </tbody>
  </table>
}

function RecoveryTrend({ rows }: { rows: Summary['recovery_trend'] }) {
  if (rows.length === 0)
    return <p className="text-slate-500 text-sm p-4">No recoveries yet.</p>
  const max = Math.max(...rows.map((r) => r.recovered), 1)
  return <div className="flex items-end gap-1 h-40 px-2">
    {rows.map((r) => {
      const h = (r.recovered / max) * 100
      return <div key={r.cycle_end} className="flex flex-col items-center flex-1 min-w-[18px]">
        <div className="w-full bg-emerald-400 rounded-t hover:bg-emerald-500 transition-colors"
             style={{ height: `${Math.max(2, h)}%` }}
             title={`${r.cycle_end}: ₹${fmt2(r.recovered)}`} />
        <span className="text-[9px] text-slate-500 mt-1">{r.cycle_end.slice(5)}</span>
      </div>
    })}
  </div>
}

function RecentCyclesTable({ rows }: { rows: Summary['cycles'] }) {
  if (rows.length === 0)
    return <p className="text-slate-500 text-sm p-4">No cycles processed yet.</p>
  return <table className="w-full text-sm">
    <thead className="bg-slate-50 text-left text-xs">
      <tr>
        <th className="px-2 py-1">Company</th>
        <th className="px-2 py-1">Cycle</th>
        <th className="px-2 py-1 text-right">Released</th>
        <th className="px-2 py-1 text-right">Rent charged</th>
        <th className="px-2 py-1 text-right">Rent collected</th>
        <th className="px-2 py-1 text-right">Rent missed</th>
        <th className="px-2 py-1 text-right">COD held</th>
      </tr>
    </thead>
    <tbody>
      {rows.slice(0, 20).map((r, i) => (
        <tr key={r.company + r.cycle_end + i} className="border-t">
          <td className="px-2 py-1">
            <span className="inline-flex items-center gap-1">
              <span className="w-2 h-2 rounded-full inline-block"
                    style={{ background: colorFor(r.company) }} />
              {r.company}
            </span>
          </td>
          <td className="px-2 py-1 text-xs">{r.cycle_start} → {r.cycle_end}</td>
          <td className="px-2 py-1 text-right font-medium">{fmt2(r.released)}</td>
          <td className="px-2 py-1 text-right">{fmt2(r.rent_charged)}</td>
          <td className="px-2 py-1 text-right text-emerald-700">{fmt2(r.rent_collected)}</td>
          <td className={'px-2 py-1 text-right ' + (r.rent_missed > 0 ? 'text-red-700' : 'text-slate-400')}>
            {fmt2(r.rent_missed)}
          </td>
          <td className={'px-2 py-1 text-right ' + (r.cod_held > 0 ? 'text-amber-700' : 'text-slate-400')}>
            {fmt2(r.cod_held)}
          </td>
        </tr>
      ))}
    </tbody>
  </table>
}
