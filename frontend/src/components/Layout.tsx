import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { useScrollRestoration } from '../state/useScrollRestoration'
import { useRouteMemory } from '../state/useRouteMemory'

export function Layout() {
  useScrollRestoration()
  useRouteMemory()
  return (
    <div className="flex min-h-screen bg-surface">
      <Sidebar />
      <main className="flex-1 min-w-0 overflow-x-auto p-6 md:p-8 animate-fade-up">
        <Outlet />
      </main>
    </div>
  )
}
