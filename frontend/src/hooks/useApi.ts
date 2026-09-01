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
 */
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

  useEffect(() => {
    if (path === null) {
      setLoading(false)
      return
    }
    const controller = new AbortController()
    setLoading(true)
    setError(null)
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
