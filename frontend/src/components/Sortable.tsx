import { useMemo, useState } from 'react'

/**
 * Spreadsheet-style sorting helpers.
 *
 *   const { sorted, sortKey, sortDir, toggleSort } = useSort(rows, 'name')
 *   <SortableTh tag="name" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort}>
 *     Name
 *   </SortableTh>
 *   …
 *   {sorted.map(...)}
 *
 * Click a header once → ascending. Click again → descending. Click a third time
 * → restores the original order.
 */
export type SortDir = 'asc' | 'desc' | null

export function useSort<T>(rows: T[], initialKey: keyof T & string = '' as keyof T & string) {
  const [sortKey, setSortKey] = useState<string>(initialKey || '')
  const [sortDir, setSortDir] = useState<SortDir>(null)

  const sorted = useMemo(() => {
    if (!sortKey || !sortDir) return rows
    const sign = sortDir === 'asc' ? 1 : -1
    const copy = [...rows]
    copy.sort((a, b) => {
      const av = (a as Record<string, unknown>)[sortKey]
      const bv = (b as Record<string, unknown>)[sortKey]
      if (av == null && bv == null) return 0
      if (av == null) return 1
      if (bv == null) return -1
      if (typeof av === 'number' && typeof bv === 'number') return sign * (av - bv)
      return sign * String(av).localeCompare(String(bv),
        undefined, { numeric: true, sensitivity: 'base' })
    })
    return copy
  }, [rows, sortKey, sortDir])

  const toggleSort = (key: string) => {
    if (sortKey !== key) { setSortKey(key); setSortDir('asc'); return }
    if (sortDir === 'asc')  { setSortDir('desc'); return }
    if (sortDir === 'desc') { setSortKey(''); setSortDir(null); return }
    setSortDir('asc')
  }

  return { sorted, sortKey, sortDir, toggleSort }
}

export function SortableTh({
  tag, sortKey, sortDir, onClick, children, right, className = '',
}: {
  tag: string
  sortKey: string
  sortDir: SortDir
  onClick: (tag: string) => void
  children: React.ReactNode
  right?: boolean
  className?: string
}) {
  const active = sortKey === tag && sortDir !== null
  const arrow = active ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''
  return (
    <th
      onClick={() => onClick(tag)}
      className={'px-3 py-2 font-medium text-xs cursor-pointer select-none ' +
        (right ? 'text-right ' : '') +
        (active ? 'text-brand ' : '') + className}
      title="Click to sort"
    >
      {children}
      <span className="text-[10px]">{arrow}</span>
    </th>
  )
}
