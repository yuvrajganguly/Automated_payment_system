import { useMemo } from 'react'

/**
 * Spreadsheet-style header filters.
 *
 * Each column gets a dropdown listing the unique values currently in that
 * column. Pick one to filter to just that value; "All" to clear. Combine
 * across columns with AND.
 *
 *   const cols = [
 *     { key: 'company', label: 'Company' },
 *     { key: 'hub',     label: 'Hub' },
 *   ]
 *   const [filters, setFilters] = useState<Record<string, string>>({})
 *   const visible = applyFilters(rows, filters)
 */

export interface FilterColumn<T> {
  key: keyof T & string
  label: string
}

export function uniqueValues<T>(rows: T[], key: keyof T & string): string[] {
  const seen = new Set<string>()
  for (const r of rows) {
    const v = r[key]
    if (v === null || v === undefined || v === '') continue
    seen.add(String(v))
  }
  return Array.from(seen).sort((a, b) =>
    a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' })
  )
}

export function applyFilters<T>(
  rows: T[],
  filters: Record<string, string>,
): T[] {
  const entries = Object.entries(filters).filter(([, v]) => v !== '')
  if (entries.length === 0) return rows
  return rows.filter((r) =>
    entries.every(([k, v]) => String((r as Record<string, unknown>)[k] ?? '') === v),
  )
}

export function ColumnFilters<T>({
  rows, columns, filters, onChange,
}: {
  rows: T[]
  columns: FilterColumn<T>[]
  filters: Record<string, string>
  onChange: (next: Record<string, string>) => void
}) {
  const optionsByCol = useMemo(() => {
    const out: Record<string, string[]> = {}
    for (const c of columns) out[c.key] = uniqueValues(rows, c.key)
    return out
  }, [rows, columns])

  const setOne = (k: string, v: string) => {
    const next = { ...filters }
    if (v === '') delete next[k]
    else next[k] = v
    onChange(next)
  }

  const anyActive = Object.values(filters).some((v) => v !== '')

  return (
    <div className="panel p-4 mb-4">
      <div className="flex flex-wrap gap-3 items-end">
        {columns.map((c) => (
          <div key={c.key} className="flex-1 min-w-[140px]">
            <label className="block text-xs font-medium mb-1">{c.label}</label>
            <select
              value={filters[c.key] ?? ''}
              onChange={(e) => setOne(c.key, e.target.value)}
              className="w-full border rounded px-3 py-2 text-sm"
            >
              <option value="">All</option>
              {optionsByCol[c.key].map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
          </div>
        ))}
        {anyActive && (
          <button
            type="button"
            onClick={() => onChange({})}
            className="text-xs text-brand underline px-2 py-2"
          >
            Clear filters
          </button>
        )}
      </div>
    </div>
  )
}
