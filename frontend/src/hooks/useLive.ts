import { useEffect, useRef, useSyncExternalStore } from 'react'
import { api } from '../api/client'

/**
 * Keeps every open page honest.
 *
 * The console painted itself once per page load. Meanwhile a recruiter
 * onboards a rider from the phone, the office looks at a roster loaded an hour
 * ago, doesn't see them, and onboards them again. So one small poll runs for
 * the whole app: `/activity/changes` returns a cursor (the last activity-log
 * id) and, given the cursor you last saw, which kinds of thing moved. When it
 * moves, every live query reloads — see `useApi`.
 *
 * A poll, not a socket: it is one indexed read, it survives a second server
 * process, and it costs nothing while the tab is in the background, where it
 * stops entirely.
 */
/**
 * How often to ask. Three seconds while anything is happening — that is the
 * window in which two people can start onboarding the same rider, so it is the
 * number that matters. When nothing has moved for a while the console is
 * probably parked on someone's second monitor, and the poll backs off; any
 * change, or the tab coming back to the front, makes it eager again.
 */
const BUSY_MS = 3_000
const CALM_MS = 10_000
const IDLE_MS = 30_000
const CALM_AFTER_MS = 2 * 60_000
const IDLE_AFTER_MS = 10 * 60_000

let cursor = 0
let changed: string[] = []
let lastChangeAt = Date.now()
let timer: ReturnType<typeof setTimeout> | null = null
let subscribers = 0
const listeners = new Set<() => void>()

function interval(): number {
  const quiet = Date.now() - lastChangeAt
  if (quiet > IDLE_AFTER_MS) return IDLE_MS
  if (quiet > CALM_AFTER_MS) return CALM_MS
  return BUSY_MS
}

function emit() {
  for (const l of listeners) l()
}

async function poll() {
  if (document.visibilityState !== 'visible') return
  try {
    const res = await api.get<{ cursor: number; changed: string[] }>(
      cursor ? `/activity/changes?since=${cursor}` : '/activity/changes',
    )
    if (res.cursor !== cursor) {
      cursor = res.cursor
      changed = res.changed
      lastChangeAt = Date.now()
      emit()
    }
  } catch {
    // Offline or signed out: the next tick tries again. Never surface this —
    // the page's own request will report a real problem in its own words.
  }
}

function schedule() {
  if (timer) clearTimeout(timer)
  timer = setTimeout(async () => {
    await poll()
    if (subscribers > 0) schedule()
  }, interval())
}

function onVisible() {
  if (document.visibilityState !== 'visible') return
  lastChangeAt = Date.now() // someone is looking: be eager again
  void poll()
  schedule()
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  if (subscribers++ === 0) {
    document.addEventListener('visibilitychange', onVisible)
    void poll()
    schedule()
  }
  return () => {
    listeners.delete(listener)
    if (--subscribers === 0) {
      document.removeEventListener('visibilitychange', onVisible)
      if (timer) clearTimeout(timer)
      timer = null
    }
  }
}

/** The current change cursor. Include it in a query's deps to follow the server. */
export function useLiveCursor(): number {
  return useSyncExternalStore(
    subscribe,
    () => cursor,
    () => 0,
  )
}

/**
 * Run [reload] whenever the server moves — for the pages that fetch by hand
 * rather than through `useApi`. Pass [kinds] ("rider", "ev", "request", …) to
 * ignore changes the page does not show.
 */
export function useLiveReload(reload: () => void, kinds?: readonly string[]): void {
  const cursor = useLiveCursor()
  const latest = useRef(reload)
  latest.current = reload
  const seen = useRef(cursor)
  useEffect(() => {
    if (cursor === seen.current) return // first render, or nothing moved
    seen.current = cursor
    if (kinds && !changed.some((k) => kinds.includes(k))) return
    latest.current()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the cursor is the trigger
  }, [cursor])
}

/** What moved since the previous cursor — "rider", "ev", "request", … */
export function lastChanged(): string[] {
  return changed
}

/** Forget the cursor on sign-out so the next session starts clean. */
export function resetLive(): void {
  cursor = 0
  changed = []
  lastChangeAt = Date.now()
}
