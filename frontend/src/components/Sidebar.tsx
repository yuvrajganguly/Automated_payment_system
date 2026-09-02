import { NavLink } from 'react-router-dom'
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

const heading = 'mt-6 mb-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500 px-3'
const linkClass = ({ isActive }: { isActive: boolean }) =>
  'relative px-3 py-[7px] rounded-lg text-[13px] leading-5 transition-colors duration-100 ' +
  (isActive
    ? 'bg-brand-500/15 text-white font-semibold ' +
      'before:absolute before:left-0 before:top-1.5 before:bottom-1.5 before:w-[3px] ' +
      'before:rounded-full before:bg-brand-400'
    : 'text-slate-400 hover:text-white hover:bg-white/5')

export function Sidebar() {
  const { user, logout } = useAuth()
  const isCreator = user?.role === 'creator'
  return (
    <aside className="w-56 shrink-0 bg-ink-900 text-slate-300 flex flex-col border-r border-black/40
                      sticky top-0 h-screen overflow-y-auto px-3 py-5">
      <div className="flex items-center gap-2.5 mb-4 px-2">
        <div className="h-8 w-8 rounded-lg bg-brand-500 grid place-items-center
                        font-display font-bold text-white text-sm">P</div>
        <span className="text-[15px] font-display font-semibold tracking-tight text-white">
          Payout
        </span>
      </div>
      <nav className="flex flex-col gap-0.5 flex-1">
        {SECTIONS.map((section, i) => (
          <div key={section.heading ?? i} className="flex flex-col gap-0.5">
            {section.heading && <div className={heading}>{section.heading}</div>}
            {section.items.map((item) => (
              <NavLink key={item.to} to={rememberedPath(item.to)} end={item.end} className={linkClass}>
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
                to={item.to}
                className={({ isActive }) =>
                  'px-3 py-[7px] rounded-lg text-[13px] transition-colors duration-100 ' +
                  (isActive
                    ? 'bg-fuchsia-500/20 text-white font-semibold'
                    : 'text-slate-400 hover:text-white hover:bg-white/5')
                }
              >
                {item.label}
              </NavLink>
            ))}
          </>
        )}
      </nav>
      <div className="mt-auto pt-4 border-t border-white/10 text-xs px-2">
        <p className="font-medium text-slate-200 truncate">{user?.email}</p>
        <div className="mt-1.5 mb-2.5 flex items-center gap-2">
          <span className={'pill ring-1 ' +
            (user?.role === 'creator' ? 'bg-fuchsia-500/15 text-fuchsia-300 ring-fuchsia-400/25'
             : user?.role === 'admin' ? 'bg-emerald-500/15 text-emerald-300 ring-emerald-400/25'
             :                          'bg-white/10 text-slate-300 ring-white/15')}>
            {user?.role}
          </span>
          <button onClick={logout}
                  className="text-[11px] text-slate-500 hover:text-white transition-colors">
            Log out
          </button>
        </div>
      </div>
    </aside>
  )
}
