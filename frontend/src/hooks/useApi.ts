import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type RequestOptions } from '../api/client'

export interface ApiState<T> {
  data: T | null
  error: string | null
  loading: boolean
  /** Re-run the request (e.g. after a mutation). */
  reload: () => void
}

/**
 * Load `path` and keep the result in state.
 *
 * - Cancels the in-flight request when `path`/`deps` change or the component
 *   unmounts, so a slow response for /persons/1 can never overwrite the data
 *   for /persons/2 (no page had this guard before).
 * - The error branch is structural — six `.then().finally()` chains used to
 *   leave the UI blank with an unhandled rejection on a network failure.
 * - Pass `null` as `path` to skip fetching (e.g. until an id is known).
 * - Refetches when the tab comes back to the front after `STALE_MS`. A console
 *   left open in a background tab used to keep showing last night's roster —
 *   a rider onboarded from the phone simply wasn't there until a manual
 *   reload, which reads as "the app didn't save it".
 */
const STALE_MS = 30_000

export function useApi<T>(
  path: string | null,
  deps: readonly unknown[] = [],
  opts: RequestOptions = {},
): ApiState<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState<boolean>(path !== null)
  const [tick, setTick] = useState(0)
  const optsRef = useRef(opts)
  optsRef.current = opts
  const fetchedAt = useRef(0)

  useEffect(() => {
    if (path === null) {
      setLoading(false)
      return
    }
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    fetchedAt.current = Date.now()
    api
      .get<T>(path, { ...optsRef.current, signal: controller.signal })
      .then((d) => {
        if (!controller.signal.aborted) setData(d)
      })
      .catch((e: unknown) => {
        if (controller.signal.aborted) return
        setError(e instanceof Error ? e.message : 'Request failed')
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- deps are the caller's cache key
  }, [path, tick, ...deps])

  useEffect(() => {
    if (path === null) return
    const refreshIfStale = () => {
      if (document.visibilityState !== 'visible') return
      if (Date.now() - fetchedAt.current < STALE_MS) return
      setTick((t) => t + 1)
    }
    document.addEventListener('visibilitychange', refreshIfStale)
    window.addEventListener('focus', refreshIfStale)
    return () => {
      document.removeEventListener('visibilitychange', refreshIfStale)
      window.removeEventListener('focus', refreshIfStale)
    }
  }, [path])

  const reload = useCallback(() => setTick((t) => t + 1), [])
  return { data, error, loading, reload }
}

export interface MutationState<A extends unknown[], R> {
  run: (...args: A) => Promise<R | undefined>
  busy: boolean
  error: string | null
  reset: () => void
}

/**
 * Wrap a write so `busy` and `error` are always set/reset correctly, and the
 * caller gets `undefined` instead of an exception on failure.
 */
export function useMutation<A extends unknown[], R>(fn: (...args: A) => Promise<R>): MutationState<A, R> {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const run = useCallback(
    async (...args: A) => {
      setBusy(true)
      setError(null)
      try {
        return await fn(...args)
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : 'Request failed')
        return undefined
      } finally {
        setBusy(false)
      }
    },
    [fn],
  )
  const reset = useCallback(() => setError(null), [])
  return { run, busy, error, reset }
}
