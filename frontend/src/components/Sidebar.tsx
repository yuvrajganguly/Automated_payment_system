import { NavLink, useLocation } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { rememberedPath } from '../state/useRouteMemory'

// Workflow-oriented navigation: the daily loop (process → review → fix) up
// top, then the registers. Provider pages (Raft/Blive) are intentionally
// absent — the routes still work (/raft, /blive) but earn no nav space.
const SECTIONS: { heading?: string; items: { to: string; label: string; end?: boolean }[] }[] = [
  { items: [
      { to: '/', label: 'Process Payout', end: true },
      { to: '/dashboard', label: 'Dashboard' },
      { to: '/corrections', label: 'Corrections' },
  ] },
  { heading: 'Riders', items: [
      { to: '/riders', label: 'Riders' },
      { to: '/inactive', label: 'Inactive' },
  ] },
  { heading: 'Fleet', items: [
      { to: '/evs', label: 'EVs' },
      { to: '/ev-rent', label: 'EV Rent Details' },
  ] },
  { heading: 'Money', items: [
      { to: '/arrears', label: 'Arrears' },
      { to: '/cod', label: 'COD' },
      { to: '/payments', label: 'Payments' },
      { to: '/transactions', label: 'Transactions' },
  ] },
  { heading: 'Admin', items: [
      { to: '/users', label: 'Users' },
      { to: '/settings', label: 'Settings' },
  ] },
]

const CREATOR_NAV = [{ to: '/system', label: 'System' }]

const heading =
  'mt-6 mb-1.5 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400/80 px-3'

const linkClass = ({ isActive }: { isActive: boolean }) =>
  'group relative px-3 py-[7px] rounded-lg text-[13px] leading-5 ' +
  'transition-all duration-150 ease-out ' +
  (isActive
    ? 'text-white font-semibold bg-gradient-to-r from-brand-500/20 to-brand-500/[0.06] ' +
      'shadow-[inset_0_1px_0_rgba(255,255,255,0.06),0_0_0_1px_rgba(57,135,229,0.22)] ' +
      'before:absolute before:left-0 before:top-1.5 before:bottom-1.5 before:w-[3px] ' +
      'before:rounded-full before:bg-brand-400 ' +
      'before:shadow-[0_0_8px_rgba(84,154,233,0.8)]'
    : 'text-slate-500 hover:text-slate-800 hover:bg-white/[0.04] hover:translate-x-[2px]')

export function Sidebar() {
  const { user, logout } = useAuth()
  const { pathname, search } = useLocation()
  const isCreator = user?.role === 'creator'

  // Route memory is written by an effect AFTER render, so at render time the
  // stored value for the CURRENT route is one navigation behind — clicking
  // the section you're already in used to reset its tabs/filters. The live
  // location is the truth for the active route; storage covers the rest.
  const linkTo = (to: string) => (pathname === to ? pathname + search : rememberedPath(to))

  return (
    <aside className="w-56 shrink-0 sticky top-0 h-screen overflow-y-auto px-3 py-5 flex flex-col
                      bg-gradient-to-b from-ink-800 to-ink-950
                      border-r border-white/[0.06]
                      shadow-[inset_-1px_0_0_rgba(255,255,255,0.03)]">
      <div className="flex items-center gap-2.5 mb-4 px-2">
        <div className="h-8 w-8 rounded-lg grid place-items-center font-display font-bold text-white text-sm
                        bg-gradient-to-br from-brand-400 to-brand-800
                        shadow-[0_0_0_1px_rgba(122,178,242,0.35),0_2px_12px_-2px_rgba(57,135,229,0.7)]">
          P
        </div>
        <span className="text-[15px] font-display font-semibold tracking-tight text-white">
          Payout
        </span>
      </div>
      <nav className="flex flex-col gap-0.5 flex-1">
        {SECTIONS.map((section, i) => (
          <div key={section.heading ?? i} className="flex flex-col gap-0.5">
            {section.heading && <div className={heading}>{section.heading}</div>}
            {section.items.map((item) => (
              <NavLink key={item.to} to={linkTo(item.to)} end={item.end} className={linkClass}>
                {item.label}
              </NavLink>
            ))}
          </div>
        ))}
        {isCreator && (
          <>
            <div className={heading}>Creator</div>
            {CREATOR_NAV.map((item) => (
              <NavLink
                key={item.to}
                to={linkTo(item.to)}
                className={({ isActive }) =>
                  'px-3 py-[7px] rounded-lg text-[13px] transition-all duration-150 ' +
                  (isActive
                    ? 'bg-fuchsia-500/15 text-white font-semibold ' +
                      'shadow-[0_0_0_1px_rgba(217,70,239,0.25)]'
                    : 'text-slate-500 hover:text-slate-800 hover:bg-white/[0.04]')
                }
              >
                {item.label}
              </NavLink>
            ))}
          </>
        )}
      </nav>
      <div className="mt-auto pt-4 border-t border-white/[0.06] text-xs px-2">
        <p className="font-medium text-slate-700 truncate">{user?.email}</p>
        <div className="mt-1.5 mb-2.5 flex items-center gap-2">
          <span className={'pill ring-1 ' +
            (user?.role === 'creator' ? 'bg-fuchsia-500/15 text-fuchsia-300 ring-fuchsia-400/25'
             : user?.role === 'admin' ? 'bg-emerald-500/15 text-emerald-300 ring-emerald-400/25'
             :                          'bg-white/10 text-slate-600 ring-white/15')}>
            {user?.role}
          </span>
          <button onClick={logout}
                  className="text-[11px] text-slate-400 hover:text-slate-800 transition-colors">
            Log out
          </button>
        </div>
      </div>
    </aside>
  )
}
