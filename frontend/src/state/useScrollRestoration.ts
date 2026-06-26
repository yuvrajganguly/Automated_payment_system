import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'

/**
 * Per-route window scroll restoration, keyed by pathname and stored in
 * sessionStorage (so it survives navigation and refresh within the tab).
 *
 * Mount once, high in the tree (Layout). On each route change it records the
 * outgoing scroll position and restores the incoming one. Because page data
 * loads asynchronously, restoration retries over a few animation frames until
 * the document is tall enough to honor the saved offset.
 */
export function useScrollRestoration() {
  const { pathname } = useLocation()

  useEffect(() => {
    const key = 'scroll:' + pathname
    const saved = parseInt(sessionStorage.getItem(key) || '0', 10) || 0

    let raf = 0
    let tries = 0
    const restore = () => {
      window.scrollTo(0, saved)
      // Keep trying until the content is tall enough (or we give up).
      if (++tries < 8 && saved > 0 && Math.abs(window.scrollY - saved) > 2) {
        raf = requestAnimationFrame(restore)
      }
    }
    raf = requestAnimationFrame(restore)

    let ticking = false
    const onScroll = () => {
      if (ticking) return
      ticking = true
      requestAnimationFrame(() => {
        sessionStorage.setItem(key, String(window.scrollY))
        ticking = false
      })
    }
    window.addEventListener('scroll', onScroll, { passive: true })

    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('scroll', onScroll)
      // Persist final position when leaving this route.
      sessionStorage.setItem(key, String(window.scrollY))
    }
  }, [pathname])
}
