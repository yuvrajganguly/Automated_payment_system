import { NavLink } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

const NAV = [
  { to: '/', label: 'Process Payout', end: true },
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/riders', label: 'Riders' },
  { to: '/evs', label: 'EVs' },
  { to: '/arrears', label: 'Arrears' },
  { to: '/cod', label: 'COD' },
  { to: '/payments', label: 'Payments' },
  { to: '/users', label: 'Users' },
  { to: '/ev-rent', label: 'EV Rent Details' },
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
       