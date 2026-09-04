import { useLayoutEffect, useRef, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { rememberedPath } from '../state/useRouteMemory'
import { workspaceFor, workspacesFor } from './workspaces'

/** The workspace's page rail, under the command bar: pages as quiet text
 *  links with one glowing indicator that SLIDES between them. */
export function SubNav() {
  const { pathname, search } = useLocation()
  const { user } = useAuth()
  const ws = workspaceFor(pathname)
  const railRef = useRef<HTMLElement>(null)
  const [bar, setBar] = useState<{ left: number; width: number } | null>(null)

  const visible = workspacesFor(user?.role).find((w) => w.key === ws.key)
  const pages = [...(visible ?? ws).pages]
  if (ws.key === 'admin' && user?.role === 'creator') {
    pages.push({ to: '/system', label: 'System' })
  }

  const activeIdx = pages.findIndex((p) =>
    p.end ? pathname === p.to : pathname === p.to || pathname.startsWith(p.to + '/'),
  )

  // Measure the active link and glide the indicator under it.
  useLayoutEffect(() => {
    const rail = railRef.current
    if (!rail) return
    const el = rail.querySelectorAll('a')[activeIdx] as HTMLElement | undefined
    if (!el) {
      setBar(null)
      return
    }
    const measure = () =>
      setBar({ left: el.offsetLeft + 8, width: Math.max(24, el.offsetWidth - 16) })
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    ro.observe(rail)
    return () => ro.disconnect()
  }, [activeIdx, pathname, pages.length])

  // Live URL for the page you're on; remembered URL for its siblings — the
  // same one-render-behind rule the old sidebar needed.
  const linkTo = (to: string) => (pathname === to ? pathname + search : rememberedPath(to))

  if (pages.length < 2) return null

  return (
    <nav
      ref={railRef}
      className="relative flex items-center gap-1 px-4 h-11 border-b border-edge-soft"
      aria-label={ws.label}
    >
      {pages.map((p) => (
        <NavLink
          key={p.to}
          to={linkTo(p.to)}
          end={p.end}
          className={({ isActive }) =>
            'px-3 py-1.5 rounded-lg text-[13px] transition-colors duration-150 ' +
            (isActive
              ? 'text-white font-semibold'
              : 'text-slate-500 hover:text-slate-800 hover:bg-white/[0.04]')
          }
        >
          {p.label}
        </NavLink>
      ))}
      {bar && (
        <span
          aria-hidden
          className="absolute bottom-0 h-[2px] rounded-full bg-gradient-to-r from-brand-400 to-brand-500
                     shadow-[0_0_10px_rgba(139,92,246,0.8)] transition-all duration-300 ease-out"
          style={{ left: bar.left, width: bar.width }}
        />
      )}
    </nav>
  )
}
