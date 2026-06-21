import { NavLink } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

const NAV = [
  { to: '/', label: 'Process Payout', end: true },
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/riders', label: 'Riders' },
  { to: '/evs', label: 'EVs' },
  { to: '/arrears', label: 'Arrears' },
  { to: '/cod', label: 'COD' },
  { to: '/inactive', label: 'Inactive' },
  { to: '/payments', label: 'Payments' },
  { to: '/users', label: 'Users' },
  { to: '/ev-rent', label: 'EV Rent Details' },
  { to: '/raft',  label: 'Raft' },
  { to: '/blive', label: 'Blive' },
  { to: '/transactions', label: 'Transactions' },
  { to: '/settings', label: 'Settings' },
]

const CREATOR_NAV = [
  { to: '/system', label: 'System', icon: '⚡' },
]

export function Sidebar() {
  const { user, logout } = useAuth()
  const isCreator = user?.role === 'creator'
  return (
    <aside className="w-60 bg-brand text-white p-6 flex flex-col">
      <h1 className="text-xl font-bold mb-8">Payout</h1>
      <nav className="flex flex-col gap-1 flex-1">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              'px-3 py-2 rounded text-sm ' +
              (isActive ? 'bg-white/20 font-semibold' : 'hover:bg-white/10')
            }
          >
            {item.label}
          </NavLink>
        ))}
        {isCreator && (
          <>
            <div className="mt-4 mb-1 text-[10px] uppercase tracking-wider text-white/40 px-3">
              Creator
            </div>
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
