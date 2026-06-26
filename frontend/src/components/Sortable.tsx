import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

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

export function useSort<T>(
  rows: T[],
  opts: { initialKey?: string; urlKey?: string } = {},
) {
  const { initialKey = '', urlKey } = opts
  const [params, setSearchParams] = useSearchParams()
  const [localKey, setLocalKey] = useState<string>(initialKey)
  const [localDir, setLocalDir] = useState<SortDir>(initialKey ? 'asc' : null)

  // When urlKey is given, sort lives in the URL (shareable, survives refresh);
  // otherwise it is component-local (back-compatible default).
  const dirKey = urlKey ? urlKey + 'Dir' : ''
  const urlDirRaw = urlKey ? params.get(dirKey) : null
  const sortKey = urlKey ? (params.get(urlKey) ?? '') : localKey
  const sortDir: SortDir =
    urlDirRaw === 'asc' || urlDirRaw === 'desc' ? urlDirRaw : urlKey ? null : localDir

  const setSort = (key: string, dir: SortDir) => {
    if (urlKey) {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          if (!key || !dir) {
            next.delete(urlKey)
            next.delete(dirKey)
          } else {
            next.set(urlKey, key)
            next.set(dirKey, dir)
          }
          return next
        },
        { replace: true },
      )
    } else {
      setLocalKey(key)
      setLocalDir(dir)
    }
  }

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
    if (sortKey !== key) { setSort(key, 'asc'); return }
    if (sortDir === 'asc')  { setSort(key, 'desc'); return }
    if (sortDir === 'desc') { setSort('', null); return }
    setSort(key, 'asc')
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
