import { NavLink } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

const NAV = [
  { to: '/', label: 'Process Payout', end: true },
  { to: '/riders', label: 'Riders' },
  { to: '/evs', label: 'EVs' },
  { to: '/arrears', label: 'Arrears' },
  { to: '/cod', label: 'COD' },
  { to: '/ev-rent', label: 'EV Rent Details' },
  { to: '/transactions', label: 'Transactions' },
  { to: '/settings', label: 'Settings' },
]

export function Sidebar() {
  const { user, logout } = useAuth()
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
      </nav>
      <div className="mt-auto pt-4 border-t border-white/20 text-xs">
        <p className="font-semibold">{user?.email}</p>
        <p className="opacity-70 mb-3">{user?.role}</p>
        <button onClick={logout} className="text-xs underline hover:opacity-80">
          Log out
        </button>
      </div>
    </aside>
  )
}
