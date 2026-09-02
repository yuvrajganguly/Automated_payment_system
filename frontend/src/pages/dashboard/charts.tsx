/**
 * Chart primitives for the analytics dashboard.
 *
 * Hand-rolled SVG (no chart lib) following a small, strict spec:
 * - 2px lines, bars ≤24px wide, 4px rounded data-ends anchored to the
 *   baseline, 2px surface gaps between stacked segments.
 * - Hairline solid grid; a single y-axis (never dual-axis).
 * - Crosshair + tooltip on every line chart, per-mark tooltip on bars.
 * - A legend whenever there are ≥2 series; text always wears ink colors,
 *   never the series color.
 *
 * Palette (validated for CVD + normal-vision separation on the light
 * surface; the aqua slot carries a contrast warning, so every chart is
 * paired with a data table in its tab):
 *   blue #2a78d6 · aqua #1baf7a · red #d03b3b · orange #eb6834
 * Red and orange are never used in the same chart (they fail the
 * normal-vision separation floor against each other).
 */
import { useRef, useState } from 'react'
import { money, moneyWhole } from '../../lib/format'

export const C = {
  blue: '#2a78d6',
  aqua: '#1baf7a',
  red: '#d03b3b',
  orange: '#eb6834',
  grid: '#e7e5e4',
  ink: '#64748b',
} as const

export interface Series {
  key: string
  label: string
  color: string
  values: number[]
}

const W = 720
const H = 220
const PAD = { top: 12, right: 16, bottom: 24, left: 56 }

function niceMax(v: number): number {
  if (v <= 0) return 1
  const pow = 10 ** Math.floor(Math.log10(v))
  for (const m of [1, 2, 2.5, 5, 10]) {
    if (m * pow >= v) return m * pow
  }
  return 10 * pow
}

const fmtTick = (v: number) =>
  Math.abs(v) >= 1000 ? moneyWhole(v) : String(Math.round(v * 10) / 10)

export function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600 mb-1">
      {items.map((it) => (
        <span key={it.label} className="inline-flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: it.color }} />
          {it.label}
        </span>
      ))}
    </div>
  )
}

interface TooltipState {
  index: number
  xPct: number
  yPct: number
}

/** Shared hover logic: maps mouse position → nearest label index. */
function useHover(count: number) {
  const ref = useRef<HTMLDivElement>(null)
  const [tip, setTip] = useState<TooltipState | null>(null)
  const onMove = (e: React.MouseEvent) => {
    const el = ref.current
    if (!el || count === 0) return
    const r = el.getBoundingClientRect()
    const fx = (e.clientX - r.left) / r.width // 0..1 across the wrapper
    const plotX = fx * W
    const innerW = W - PAD.left - PAD.right
    const step = count > 1 ? innerW / (count - 1) : innerW
    const idx = Math.max(0, Math.min(count - 1, Math.round((plotX - PAD.left) / step)))
    setTip({
      index: idx,
      xPct: ((PAD.left + idx * step) / W) * 100,
      yPct: ((e.clientY - r.top) / r.height) * 100,
    })
  }
  return { ref, tip, onMove, onLeave: () => setTip(null) }
}

function TooltipBox({
  tip,
  title,
  rows,
}: {
  tip: TooltipState
  title: string
  rows: { label: string; color?: string; value: string }[]
}) {
  const left = tip.xPct > 60 ? undefined : `calc(${tip.xPct}% + 10px)`
  const right = tip.xPct > 60 ? `calc(${100 - tip.xPct}% + 10px)` : undefined
  return (
    <div
      className="absolute z-20 pointer-events-none bg-white border border-slate-200 shadow-lg rounded-md px-2.5 py-1.5 text-xs"
      style={{ left, right, top: `${Math.min(tip.yPct, 55)}%` }}
    >
      <p className="font-medium text-slate-700 mb-0.5">{title}</p>
      {rows.map((r) => (
        <p key={r.label} className="flex items-center gap-1.5 text-slate-600 whitespace-nowrap">
          {r.color && (
            <span className="w-2 h-2 rounded-full shrink-0" style={{ background: r.color }} />
          )}
          <span>{r.label}</span>
          <span className="ml-auto pl-3 font-mono text-slate-800">{r.value}</span>
        </p>
      ))}
    </div>
  )
}

function Grid({ max, min = 0 }: { max: number; min?: number }) {
  const innerH = H - PAD.top - PAD.bottom
  const span = max - min || 1
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => min + f * span)
  return (
    <g>
      {ticks.map((v) => {
        const y = PAD.top + innerH - ((v - min) / span) * innerH
        return (
          <g key={v}>
            <line x1={PAD.left} y1={y} x2={W - PAD.right} y2={y} stroke={C.grid} strokeWidth="1" />
            <text x={PAD.left - 6} y={y + 3} textAnchor="end" fontSize="10" fill={C.ink}>
              {fmtTick(v)}
            </text>
          </g>
        )
      })}
    </g>
  )
}

function XLabels({ labels }: { labels: string[] }) {
  const innerW = W - PAD.left - PAD.right
  const step = labels.length > 1 ? innerW / (labels.length - 1) : innerW
  const every = Math.ceil(labels.length / 10)
  return (
    <g>
      {labels.map((l, i) =>
        i % every === 0 ? (
          <text
            key={i}
            x={PAD.left + i * step}
            y={H - 6}
            textAnchor="middle"
            fontSize="9"
            fill={C.ink}
          >
            {l}
          </text>
        ) : null,
      )}
    </g>
  )
}

// ── multi-series line chart with crosshair + tooltip ─────────────────────

export function LineChart({
  labels,
  series,
  format = money,
  height = 'h-56',
}: {
  labels: string[]
  series: Series[]
  format?: (v: number) => string
  height?: string
}) {
  const { ref, tip, onMove, onLeave } = useHover(labels.length)
  if (labels.length === 0)
    return <p className="text-slate-400 text-sm p-6 text-center">No data in this window.</p>
  const max = niceMax(Math.max(...series.flatMap((s) => s.values), 1))
  const innerW = W - PAD.left - PAD.right
  const innerH = H - PAD.top - PAD.bottom
  const step = labels.length > 1 ? innerW / (labels.length - 1) : innerW
  const x = (i: number) => PAD.left + i * step
  const y = (v: number) => PAD.top + innerH - (v / max) * innerH
  return (
    <div ref={ref} className="relative" onMouseMove={onMove} onMouseLeave={onLeave}>
      {series.length > 1 && <Legend items={series} />}
      <svg viewBox={`0 0 ${W} ${H}`} className={`w-full ${height}`} role="img">
        <Grid max={max} />
        <XLabels labels={labels} />
        {tip && (
          <line
            x1={x(tip.index)}
            y1={PAD.top}
            x2={x(tip.index)}
            y2={PAD.top + innerH}
            stroke="#94a3b8"
            strokeWidth="1"
          />
        )}
        {series.map((s) => (
          <path
            key={s.key}
            d={s.values.map((v, i) => `${i === 0 ? 'M' : 'L'} ${x(i)} ${y(v)}`).join(' ')}
            stroke={s.color}
            strokeWidth="2"
            fill="none"
            strokeLinejoin="round"
          />
        ))}
        {tip &&
          series.map((s) => (
            <circle
              key={s.key}
              cx={x(tip.index)}
              cy={y(s.values[tip.index] ?? 0)}
              r="4"
              fill={s.color}
              stroke="#fcfcfb"
              strokeWidth="2"
            />
          ))}
      </svg>
      {tip && (
        <TooltipBox
          tip={tip}
          title={labels[tip.index]}
          rows={series.map((s) => ({
            label: s.label,
            color: s.color,
            value: format(s.values[tip.index] ?? 0),
          }))}
        />
      )}
    </div>
  )
}

// ── stacked bars (2px surface gaps, rounded top of the stack) ────────────

export function StackedBarChart({
  labels,
  series,
  format = money,
}: {
  labels: string[]
  /** bottom → top stacking order */
  series: Series[]
  format?: (v: number) => string
}) {
  const { ref, tip, onMove, onLeave } = useHover(labels.length)
  if (labels.length === 0)
    return <p className="text-slate-400 text-sm p-6 text-center">No data in this window.</p>
  const totals = labels.map((_, i) => series.reduce((a, s) => a + (s.values[i] ?? 0), 0))
  const max = niceMax(Math.max(...totals, 1))
  const innerW = W - PAD.left - PAD.right
  const innerH = H - PAD.top - PAD.bottom
  const step = labels.length > 1 ? innerW / (labels.length - 1) : innerW
  const barW = Math.min(24, Math.max(6, step * 0.55))
  const scale = (v: number) => (v / max) * innerH
  return (
    <div ref={ref} className="relative" onMouseMove={onMove} onMouseLeave={onLeave}>
      <Legend items={series} />
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-56" role="img">
        <Grid max={max} />
        <XLabels labels={labels} />
        {labels.map((_, i) => {
          const cx = PAD.left + i * step
          let acc = 0
          const segs = series
            .map((s) => {
              const v = s.values[i] ?? 0
              const h = scale(v)
              const y0 = PAD.top + innerH - acc - h
              acc += h
              return { s, v, h, y0 }
            })
            .filter((g) => g.h > 0)
          const top = segs[segs.length - 1]
          return (
            <g key={i} opacity={tip && tip.index !== i ? 0.55 : 1}>
              {segs.map((g, j) => {
                const isTop = j === segs.length - 1
                const x0 = cx - barW / 2
                if (isTop && top && g.h >= 4) {
                  // rounded 4px data-end on the top of the stack only
                  const r = 4
                  return (
                    <path
                      key={g.s.key}
                      d={`M ${x0} ${g.y0 + g.h} L ${x0} ${g.y0 + r} Q ${x0} ${g.y0} ${x0 + r} ${g.y0} L ${x0 + barW - r} ${g.y0} Q ${x0 + barW} ${g.y0} ${x0 + barW} ${g.y0 + r} L ${x0 + barW} ${g.y0 + g.h} Z`}
                      fill={g.s.color}
                      stroke="#fcfcfb"
                      strokeWidth="1"
                    />
                  )
                }
                return (
                  <rect
                    key={g.s.key}
                    x={x0}
                    y={g.y0}
                    width={barW}
                    height={g.h}
                    fill={g.s.color}
                    stroke="#fcfcfb"
                    strokeWidth="1"
                  />
                )
              })}
            </g>
          )
        })}
      </svg>
      {tip && (
        <TooltipBox
          tip={tip}
          title={labels[tip.index]}
          rows={[
            ...[...series].reverse().map((s) => ({
              label: s.label,
              color: s.color,
              value: format(s.values[tip.index] ?? 0),
            })),
            { label: 'Total', value: format(totals[tip.index] ?? 0) },
          ]}
        />
      )}
    </div>
  )
}

// ── diverging bars around a zero line ────────────────────────────────────

export function DivergingBarChart({
  labels,
  values,
  posLabel,
  negLabel,
  posColor = C.blue,
  negColor = C.red,
  format = money,
}: {
  labels: string[]
  values: number[]
  posLabel: string
  negLabel: string
  posColor?: string
  negColor?: string
  format?: (v: number) => string
}) {
  const { ref, tip, onMove, onLeave } = useHover(labels.length)
  if (labels.length === 0)
    return <p className="text-slate-400 text-sm p-6 text-center">No data in this window.</p>
  const absMax = niceMax(Math.max(...values.map((v) => Math.abs(v)), 1))
  const innerW = W - PAD.left - PAD.right
  const innerH = H - PAD.top - PAD.bottom
  const zeroY = PAD.top + innerH / 2
  const step = labels.length > 1 ? innerW / (labels.length - 1) : innerW
  const barW = Math.min(24, Math.max(6, step * 0.55))
  return (
    <div ref={ref} className="relative" onMouseMove={onMove} onMouseLeave={onLeave}>
      <Legend
        items={[
          { label: posLabel, color: posColor },
          { label: negLabel, color: negColor },
        ]}
      />
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-56" role="img">
        {[absMax, absMax / 2, 0, -absMax / 2, -absMax].map((v) => {
          const y = zeroY - (v / absMax) * (innerH / 2)
          return (
            <g key={v}>
              <line
                x1={PAD.left}
                y1={y}
                x2={W - PAD.right}
                y2={y}
                stroke={v === 0 ? '#94a3b8' : C.grid}
                strokeWidth="1"
              />
              <text x={PAD.left - 6} y={y + 3} textAnchor="end" fontSize="10" fill={C.ink}>
                {fmtTick(v)}
              </text>
            </g>
          )
        })}
        <XLabels labels={labels} />
        {values.map((v, i) => {
          if (v === 0) return null
          const h = (Math.abs(v) / absMax) * (innerH / 2)
          const x0 = PAD.left + i * step - barW / 2
          const yTop = v > 0 ? zeroY - h : zeroY
          const r = Math.min(4, h)
          const d =
            v > 0
              ? `M ${x0} ${zeroY} L ${x0} ${yTop + r} Q ${x0} ${yTop} ${x0 + r} ${yTop} L ${x0 + barW - r} ${yTop} Q ${x0 + barW} ${yTop} ${x0 + barW} ${yTop + r} L ${x0 + barW} ${zeroY} Z`
              : `M ${x0} ${zeroY} L ${x0} ${yTop + h - r} Q ${x0} ${yTop + h} ${x0 + r} ${yTop + h} L ${x0 + barW - r} ${yTop + h} Q ${x0 + barW} ${yTop + h} ${x0 + barW} ${yTop + h - r} L ${x0 + barW} ${zeroY} Z`
          return (
            <path
              key={i}
              d={d}
              fill={v > 0 ? posColor : negColor}
              opacity={tip && tip.index !== i ? 0.55 : 1}
            />
          )
        })}
      </svg>
      {tip && (
        <TooltipBox
          tip={tip}
          title={labels[tip.index]}
          rows={[
            {
              label: (values[tip.index] ?? 0) >= 0 ? posLabel : negLabel,
              color: (values[tip.index] ?? 0) >= 0 ? posColor : negColor,
              value: format(Math.abs(values[tip.index] ?? 0)),
            },
          ]}
        />
      )}
    </div>
  )
}

// ── horizontal bars (aging buckets, provider comparisons) ────────────────

export function HBars({
  rows,
  color = C.blue,
  format = money,
}: {
  rows: { label: string; value: number; note?: string }[]
  color?: string
  format?: (v: number) => string
}) {
  const max = Math.max(...rows.map((r) => Math.abs(r.value)), 1)
  return (
    <div className="space-y-2">
      {rows.map((r) => (
        <div key={r.label} className="flex items-center gap-2 text-xs">
          <span className="w-16 shrink-0 text-slate-500">{r.label}</span>
          <div className="flex-1 h-4 bg-slate-100 rounded overflow-hidden">
            <div
              className="h-full rounded-r"
              style={{
                width: `${(Math.abs(r.value) / max) * 100}%`,
                background: r.value >= 0 ? color : C.red,
                minWidth: r.value !== 0 ? '2px' : 0,
              }}
              title={format(r.value)}
            />
          </div>
          <span className="w-28 shrink-0 text-right font-mono text-slate-700">
            {format(r.value)}
          </span>
          {r.note !== undefined && (
            <span className="w-20 shrink-0 text-right text-slate-400">{r.note}</span>
          )}
        </div>
      ))}
    </div>
  )
}
