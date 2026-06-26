import { NavLink } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { rememberedPath } from '../state/useRouteMemory'

const SECTIONS: { heading?: string; items: { to: string; label: string; end?: boolean }[] }[] = [
  { items: [
      { to: '/', label: 'Process Payout', end: true },
      { to: '/dashboard', label: 'Dashboard' },
  ] },
  { heading: 'Riders & Fleet', items: [
      { to: '/riders', label: 'Riders' },
      { to: '/evs', label: 'EVs' },
      { to: '/ev-rent', label: 'EV Rent Details' },
      { to: '/inactive', label: 'Inactive' },
  ] },
  { heading: 'Collections', items: [
      { to: '/arrears', label: 'Arrears' },
      { to: '/cod', label: 'COD' },
      { to: '/payments', label: 'Payments' },
      { to: '/transactions', label: 'Transactions' },
  ] },
  { heading: 'Providers', items: [
      { to: '/raft', label: 'Raft' },
      { to: '/blive', label: 'Blive' },
  ] },
  { heading: 'Admin', items: [
      { to: '/users', label: 'Users' },
      { to: '/settings', label: 'Settings' },
  ] },
]

const CREATOR_NAV = [{ to: '/system', label: 'System', icon: '⚡' }]

const heading = 'mt-5 mb-1 text-[10px] uppercase tracking-[0.15em] text-silver-500/70 px-3'
const linkClass =
  ({ isActive }: { isActive: boolean }) =>
    'px-3 py-2 rounded-lg text-sm transition-all duration-150 ' +
    (isActive
      ? 'bg-white/10 text-white font-semibold shadow-inner ring-1 ring-white/10'
      : 'text-silver-300 hover:text-white hover:bg-white/5 hover:translate-x-0.5')

export function Sidebar() {
  const { user, logout } = useAuth()
  const isCreator = user?.role === 'creator'
  return (
    <aside className="w-60 m-3 rounded-2xl bg-gradient-to-b from-midnight-800 to-midnight-950
                      text-silver-200 p-5 flex flex-col border border-white/10 shadow-glow">
      <div className="flex items-center gap-2.5 mb-7 px-1">
        <div className="h-9 w-9 rounded-xl bg-white/10 ring-1 ring-white/15 grid place-items-center
                        font-display font-bold text-white">P</div>
        <span className="text-lg font-display font-semibold tracking-tight text-white">Payout</span>
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
                  'px-3 py-2 rounded-lg text-sm flex items-center gap-2 transition-all duration-150 ' +
                  (isActive
                    ? 'bg-fuchsia-500/20 text-white font-semibold ring-1 ring-fuchsia-400/30'
                    : 'text-silver-300 hover:text-white hover:bg-white/5')
                }
              >
                <span>{item.icon}</span>
                {item.label}
              </NavLink>
            ))}
          </>
        )}
      </nav>
      <div className="mt-auto pt-4 border-t border-white/10 text-xs">
        <p className="font-semibold text-white truncate">{user?.email}</p>
        <p className="mb-3 mt-1">
          <span className={'inline-block text-[10px] px-1.5 py-0.5 rounded ring-1 ' +
            (user?.role === 'creator' ? 'bg-fuchsia-500/20 text-fuchsia-200 ring-fuchsia-400/30'
             : user?.role === 'admin' ? 'bg-emerald-500/20 text-emerald-200 ring-emerald-400/30'
             :                          'bg-white/10 text-silver-200 ring-white/15')}>
            {user?.role}
          </span>
        </p>
        <button onClick={logout}
                className="text-xs text-silver-400 hover:text-white underline transition-colors">
          Log out
        </button>
      </div>
    </aside>
  )
}
