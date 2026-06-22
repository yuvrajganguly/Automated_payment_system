import { NavLink } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

// Grouped for hierarchy. The first section has no heading (primary actions);
// the rest are labelled. Creator-only items live in their own gated section.
const SECTIONS: { heading?: string; items: { to: string; label: string; end?: boolean }[] }[] = [
  {
    items: [
      { to: '/', label: 'Process Payout', end: true },
      { to: '/dashboard', label: 'Dashboard' },
    ],
  },
  {
    heading: 'Riders & Fleet',
    items: [
      { to: '/riders', label: 'Riders' },
      { to: '/evs', label: 'EVs' },
      { to: '/ev-rent', label: 'EV Rent Details' },
      { to: '/inactive', label: 'Inactive' },
    ],
  },
  {
    heading: 'Collections',
    items: [
      { to: '/arrears', label: 'Arrears' },
      { to: '/cod', label: 'COD' },
      { to: '/payments', label: 'Payments' },
      { to: '/transactions', label: 'Transactions' },
    ],
  },
  {
    heading: 'Providers',
    items: [
      { to: '/raft', label: 'Raft' },
      { to: '/blive', label: 'Blive' },
    ],
  },
  {
    heading: 'Admin',
    items: [
      { to: '/users', label: 'Users' },
      { to: '/settings', label: 'Settings' },
    ],
  },
]

const CREATOR_NAV = [{ to: '/system', label: 'System', icon: '⚡' }]

const heading = 'mt-4 mb-1 text-[10px] uppercase tracking-wider text-white/40 px-3'
const linkClass =
  ({ isActive }: { isActive: boolean }) =>
    'px-3 py-2 rounded text-sm ' +
    (isActive ? 'bg-white/20 font-semibold' : 'hover:bg-white/10')

export function Sidebar() {
  const { user, logout } = useAuth()
  const isCreator = user?.role === 'creator'
  return (
    <aside className="w-60 bg-gradient-to-b from-brand-700 to-brand-900 text-white p-6 flex flex-col border-r border-black/10">
      <div className="flex items-center gap-2.5 mb-7">
        <div className="h-8 w-8 rounded-lg bg-white/15 grid place-items-center text-sm font-bold">P</div>
        <span className="text-lg font-semibold tracking-tight">Payout</span>
      </div>
      <nav className="flex flex-col gap-0.5 flex-1">
        {SECTIONS.map((section, i) => (
          <div key={section.heading ?? i} className="flex flex-col gap-0.5">
            {section.heading && <div className={heading}>{section.heading}</div>}
            {section.items.map((item) => (
              <NavLink key={item.to} to={item.to} end={item.end} className={linkClass}>
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
                  'px-3 py-2 rounded text-sm flex items-center gap-2 ' +
                  (isActive ? 'bg-purple-500/30 font-semibold' : 'hover:bg-white/10')
                }
              >
                <span>{item.icon}</span>
                {item.label}
              </NavLink>
            ))}
          </>
        )}
      </nav>
      <div className="mt-auto pt-4 border-t border-white/20 text-xs">
        <p className="font-semibold">{user?.email}</p>
        <p className="mb-3">
          <span className={'inline-block text-[10px] px-1.5 py-0.5 rounded ' +
            (user?.role === 'creator' ? 'bg-purple-500 text-white'
             : user?.role === 'admin' ? 'bg-emerald-500 text-white'
             :                          'bg-white/20 text-white')}>
            {user?.role}
          </span>
        </p>
        <button onClick={logout} className="text-xs underline hover:opacity-80">
          Log out
        </button>
      </div>
    </aside>
  )
}
