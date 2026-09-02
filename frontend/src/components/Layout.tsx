import { useEffect, useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { TopBar } from './TopBar'
import { SubNav } from './SubNav'
import { CommandPalette } from './CommandPalette'
import { useScrollRestoration } from '../state/useScrollRestoration'
import { useRouteMemory } from '../state/useRouteMemory'
import { rememberWorkspaceUrl, workspaceFor } from './workspaces'

/** App shell, second generation: a fixed glass command bar (workspaces +
 *  ⌘K), a per-workspace page rail, and the content canvas. No sidebar. */
export function Layout() {
  useScrollRestoration()
  useRouteMemory()
  const { pathname, search } = useLocation()
  const [paletteOpen, setPaletteOpen] = useState(false)

  // Workspace memory: switching back to a workspace lands on the exact URL
  // you left it at.
  useEffect(() => {
    rememberWorkspaceUrl(workspaceFor(pathname).key, pathname + search)
  }, [pathname, search])

  // ⌘K / Ctrl+K opens the palette from anywhere.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPaletteOpen((v) => !v)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div className="min-h-screen">
      <TopBar onOpenPalette={() => setPaletteOpen(true)} />
      <div className="pt-14">
        <div className="sticky top-14 z-30 glass-bar !border-b-0">
          <SubNav />
        </div>
        {/* Keyed by pathname so every page ENTERS — a fast, subtle rise. */}
        <main key={pathname} className="p-6 md:px-10 md:py-8 animate-fade-up">
          <Outlet />
        </main>
      </div>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  )
}
