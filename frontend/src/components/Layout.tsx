import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { useScrollRestoration } from '../state/useScrollRestoration'
import { useRouteMemory } from '../state/useRouteMemory'

export function Layout() {
  useScrollRestoration()
  useRouteMemory()
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <main className="flex-1 overflow-x-auto my-3 mr-3 rounded-2xl bg-slate-100/85
                       backdrop-blur-xl border border-white/40 shadow-glass p-6 md:p-8
                       animate-fade-up">
        <Outlet />
      </main>
    </div>
  )
}
