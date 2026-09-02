import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { WORKSPACES, workspaceFor, workspaceUrl } from './workspaces'
import emblem from '../assets/qwikserve-emblem.png'

/** The command bar: brand mark · workspace switcher · ⌘K · identity.
 *  Fixed, glass, and the only chrome above the content. */
export function TopBar({ onOpenPalette }: { onOpenPalette: () => void }) {
  const { user, logout } = useAuth()
  const { pathname, search } = useLocation()
  const navigate = useNavigate()
  const active = workspaceFor(pathname)
  const isCreator = user?.role === 'creator'

  return (
    <header className="glass-bar fixed top-0 inset-x-0 z-40 h-14 flex items-center gap-4 px-4">
      <Link to="/" className="flex items-center gap-2.5 shrink-0 group">
        <img
          src={emblem}
          alt="QwikServe"
          className="h-8 w-auto drop-shadow-[0_0_10px_rgba(220,38,38,0.45)]
                     transition-transform group-hover:scale-105"
        />
        <span className="font-display font-semibold tracking-tight text-white text-[15px]
                         hidden md:block">
          QwikServe
        </span>
      </Link>

      {/* Workspace switcher — the app's spine. */}
      <nav className="flex items-center gap-0.5 mx-auto rounded-xl p-1
                      bg-white/[0.03] border border-edge">
        {WORKSPACES.map((ws) => {
          const isActive = ws.key === active.key
          // Live URL for the workspace you're in (its memory effect runs
          // after render); stored last-visited URL for the others.
          const href = isActive ? pathname + search : workspaceUrl(ws)
          return (
            <button
              key={ws.key}
              onClick={() => navigate(href)}
              aria-current={isActive ? 'page' : undefined}
              className={
                'relative px-3 py-1.5 rounded-lg text-[13px] font-medium transition-all duration-150 ' +
                (isActive
                  ? 'text-white bg-gradient-to-b from-brand-500/30 to-brand-500/10 ' +
                    'shadow-[inset_0_1px_0_rgba(255,255,255,0.08),0_0_0_1px_rgba(139,92,246,0.35),0_0_14px_-4px_rgba(139,92,246,0.6)]'
                  : 'text-slate-500 hover:text-slate-800 hover:bg-white/[0.05]')
              }
            >
              {ws.label}
            </button>
          )
        })}
      </nav>

      <div className="flex items-center gap-2.5 shrink-0">
        <button
          onClick={onOpenPalette}
          className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-[12px]
                     text-slate-500 bg-white/[0.03] border border-edge
                     hover:text-slate-800 hover:border-edge-strong transition-all"
          title="Jump anywhere (Ctrl+K)"
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               strokeWidth="2.4" strokeLinecap="round">
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" />
          </svg>
          <span className="hidden lg:block">Jump to…</span>
          <kbd className="hidden lg:block font-mono text-[10px] px-1 py-px rounded
                          bg-white/[0.06] border border-edge">
            ⌘K
          </kbd>
        </button>
        <div className="h-5 w-px bg-edge hidden sm:block" />
        <div className="hidden sm:flex items-center gap-2">
          <span
            className={
              'h-7 w-7 rounded-full grid place-items-center text-[11px] font-bold uppercase ' +
              (isCreator
                ? 'bg-fuchsia-500/20 text-fuchsia-300 ring-1 ring-fuchsia-400/30'
                : 'bg-brand-500/20 text-brand-300 ring-1 ring-brand-400/30')
            }
            title={`${user?.email} · ${user?.role}`}
          >
            {(user?.email ?? '?')[0]}
          </span>
          <button
            onClick={logout}
            className="text-[11px] text-slate-500 hover:text-slate-800 transition-colors"
          >
            Log out
          </button>
        </div>
      </div>
    </header>
  )
}
