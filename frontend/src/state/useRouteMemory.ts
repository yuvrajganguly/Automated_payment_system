import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'

/**
 * Remembers the last full URL (pathname + query) for each route, so returning
 * to a section via the sidebar restores the exact view you left — the piece
 * URL state alone can't provide, because sidebar links point at bare paths.
 *
 * `useRouteMemory()` records; `rememberedPath(to)` reads. Keyed by exact
 * pathname, so list routes (`/evs`) and detail routes (`/evs/123`) stay
 * independent, and the sidebar's `/evs` link returns to the filtered list.
 */
const PREFIX = 'routemem:'

export function useRouteMemory() {
  const { pathname, search } = useLocation()
  useEffect(() => {
    try {
      sessionStorage.setItem(PREFIX + pathname, pathname + search)
    } catch {
      /* ignore storage errors */
    }
  }, [pathname, search])
}

export function rememberedPath(to: string): string {
  try {
    return sessionStorage.getItem(PREFIX + to) || to
  } catch {
    return to
  }
}
