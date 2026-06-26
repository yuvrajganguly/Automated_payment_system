import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'

/**
 * Typed wrappers over `useSearchParams` for *shareable* view state — filters,
 * search, sort, pagination, date ranges. The URL is the single source of
 * truth, so this state is bookmarkable, survives refresh, and Back/Forward
 * behave correctly. Each setter updates only its own key (preserving the
 * others) and uses `replace` so routine filter tweaks don't flood history.
 *
 * Every hook returns a `[value, setValue]` tuple and the setter accepts either
 * a value or an updater function `(prev) => next`, exactly mirroring
 * `useState` — so swapping a `useState` call for one of these is a one-liner.
 */
type Updater<T> = T | ((prev: T) => T)

function resolve<T>(next: Updater<T>, prev: T): T {
  return typeof next === 'function' ? (next as (p: T) => T)(prev) : next
}

function useSetParam() {
  const [, setSearchParams] = useSearchParams()
  return useCallback(
    (key: string, value: string | null) => {
      setSearchParams(
        (prev) => {
          const params = new URLSearchParams(prev)
          if (value === null || value === '') params.delete(key)
          else params.set(key, value)
          return params
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )
}

export function useUrlString(
  key: string,
  fallback = '',
): [string, (v: Updater<string>) => void] {
  const [params] = useSearchParams()
  const setParam = useSetParam()
  const value = params.get(key) ?? fallback
  const set = useCallback(
    (v: Updater<string>) => {
      const r = resolve(v, value)
      setParam(key, r || null)
    },
    [setParam, key, value],
  )
  return [value, set]
}

export function useUrlNumber(
  key: string,
  fallback: number,
): [number, (v: Updater<number>) => void] {
  const [params] = useSearchParams()
  const setParam = useSetParam()
  const raw = params.get(key)
  const parsed = raw === null || raw === '' ? fallback : Number(raw)
  const value = Number.isNaN(parsed) ? fallback : parsed
  const set = useCallback(
    (v: Updater<number>) => {
      const r = resolve(v, value)
      setParam(key, r === fallback ? null : String(r))
    },
    [setParam, key, value, fallback],
  )
  return [value, set]
}

export function useUrlBool(
  key: string,
  fallback: boolean,
): [boolean, (v: Updater<boolean>) => void] {
  const [params] = useSearchParams()
  const setParam = useSetParam()
  const raw = params.get(key)
  const value = raw === null ? fallback : raw === '1'
  const set = useCallback(
    (v: Updater<boolean>) => {
      const r = resolve(v, value)
      setParam(key, r === fallback ? null : r ? '1' : '0')
    },
    [setParam, key, value, fallback],
  )
  return [value, set]
}

export function useUrlList(
  key: string,
  fallback: string[] = [],
): [string[], (v: Updater<string[]>) => void] {
  const [params] = useSearchParams()
  const setParam = useSetParam()
  const raw = params.get(key)
  // Memoized by raw so the array reference is stable between renders.
  const value = useMemo(() => (raw ? raw.split(',').filter(Boolean) : fallback), [raw])
  const set = useCallback(
    (v: Updater<string[]>) => {
      const r = resolve(v, value)
      setParam(key, r.length ? r.join(',') : null)
    },
    [setParam, key, value],
  )
  return [value, set]
}

export function useUrlRecord(
  key: string,
  fallback: Record<string, string> = {},
): [Record<string, string>, (v: Updater<Record<string, string>>) => void] {
  const [params] = useSearchParams()
  const setParam = useSetParam()
  const raw = params.get(key)
  const value = useMemo(() => {
    if (!raw) return fallback
    try {
      return JSON.parse(raw) as Record<string, string>
    } catch {
      return fallback
    }
  }, [raw])
  const set = useCallback(
    (v: Updater<Record<string, string>>) => {
      const r = resolve(v, value)
      const clean = Object.fromEntries(Object.entries(r).filter(([, val]) => val !== ''))
      setParam(key, Object.keys(clean).length ? JSON.stringify(clean) : null)
    },
    [setParam, key, value],
  )
  return [value, set]
}
