import { useCallback, useRef, useState } from 'react'

type Updater<T> = T | ((prev: T) => T)

function read<T>(storage: Storage, key: string, fallback: T): T {
  try {
    const raw = storage.getItem(key)
    return raw === null ? fallback : (JSON.parse(raw) as T)
  } catch {
    return fallback
  }
}

/**
 * `useState` backed by Web Storage (sessionStorage by default).
 *
 * Survives route unmount/remount AND page refresh within the same tab — the
 * right home for UI state that should persist but does not belong in the URL
 * (expanded sections, drafts, transient selections). The returned API mirrors
 * `useState`, so swapping a `useState` call for this is a one-line change.
 *
 * Pass `localStorage` as the third arg for state that should also survive a
 * full browser restart (and leak across tabs) — use sparingly.
 */
export function usePersistedState<T>(
  key: string,
  initial: T,
  storage: Storage = sessionStorage,
): [T, (next: Updater<T>) => void] {
  const [value, setValue] = useState<T>(() => read(storage, key, initial))
  // Stable setter (does not change identity) -> fewer downstream re-renders.
  const storageRef = useRef(storage)
  storageRef.current = storage

  const set = useCallback(
    (next: Updater<T>) => {
      setValue((prev) => {
        const resolved =
          typeof next === 'function' ? (next as (p: T) => T)(prev) : next
        try {
          storageRef.current.setItem(key, JSON.stringify(resolved))
        } catch {
          /* storage full / unavailable - keep in-memory value */
        }
        return resolved
      })
    },
    [key],
  )

  return [value, set]
}
