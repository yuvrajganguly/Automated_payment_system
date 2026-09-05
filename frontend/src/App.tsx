import { Suspense, lazy, useEffect } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { ProtectedRoute } from './auth/ProtectedRoute'
import { Layout } from './components/Layout'
import { Spinner } from './components/Spinner'
import { LoginPage } from './pages/LoginPage'

// Route-level code splitting: the login screen used to download all 20 pages
// (DashboardPage's SVG charts, the 950-line PersonPage, …) before rendering.
const chunkLoaders: (() => Promise<unknown>)[] = []
const page = <T extends object, K extends keyof T>(load: () => Promise<T>, name: K) => {
  chunkLoaders.push(load)
  return lazy(() => load().then((m) => ({ default: m[name] as unknown as React.ComponentType })))
}

/** Route chunks are code-split so login stays light — but a chunk fetched on
 *  CLICK reads as a slow page switch. Warm them all shortly after the app is
 *  interactive; by the time anyone navigates, every page is already local. */
function usePrefetchRoutes() {
  useEffect(() => {
    const warm = () => chunkLoaders.forEach((load) => load().catch(() => {}))
    const idle = (window as { requestIdleCallback?: (cb: () => void) => number })
      .requestIdleCallback
    const t = setTimeout(() => (idle ? idle(warm) : warm()), 1200)
    return () => clearTimeout(t)
  }, [])
}

const ForgotPasswordPage = page(() => import('./pages/ForgotPasswordPage'), 'ForgotPasswordPage')
const ProcessPayoutPage = page(() => import('./pages/ProcessPayoutPage'), 'ProcessPayoutPage')
const RidersPage = page(() => import('./pages/RidersPage'), 'RidersPage')
const PersonPage = page(() => import('./pages/PersonPage'), 'PersonPage')
const EVsPage = page(() => import('./pages/EVsPage'), 'EVsPage')
const EvProfilePage = page(() => import('./pages/EvProfilePage'), 'EvProfilePage')
const ArrearsPage = page(() => import('./pages/ArrearsPage'), 'ArrearsPage')
const TransactionsPage = page(() => import('./pages/TransactionsPage'), 'TransactionsPage')
const InactivePage = page(() => import('./pages/InactivePage'), 'InactivePage')
const CodPage = page(() => import('./pages/CodPage'), 'CodPage')
const PaymentsPage = page(() => import('./pages/PaymentsPage'), 'PaymentsPage')
const DashboardPage = page(() => import('./pages/DashboardPage'), 'DashboardPage')
const CompanyPage = page(() => import('./pages/CompanyPage'), 'CompanyPage')
const CorrectionsPage = page(() => import('./pages/CorrectionsPage'), 'CorrectionsPage')
const EvRentPage = page(() => import('./pages/EvRentPage'), 'EvRentPage')
const SettingsPage = page(() => import('./pages/SettingsPage'), 'SettingsPage')
const RequestsPage = page(() => import('./pages/RequestsPage'), 'RequestsPage')
const UsersPage = page(() => import('./pages/UsersPage'), 'UsersPage')
const SystemPage = page(() => import('./pages/SystemPage'), 'SystemPage')
const RaftPage = page(() => import('./pages/RaftPage'), 'RaftPage')
const BlivePage = page(() => import('./pages/BlivePage'), 'BlivePage')

export default function App() {
  usePrefetchRoutes()
  return (
    <Suspense fallback={<div className="p-8"><Spinner /></div>}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route element={<ProtectedRoute />}>
          <Route element={<Layout />}>
            <Route path="/" element={<ProcessPayoutPage />} />
            <Route path="/riders" element={<RidersPage />} />
            <Route path="/persons/:id" element={<PersonPage />} />
            <Route path="/evs" element={<EVsPage />} />
            <Route path="/evs/:id" element={<EvProfilePage />} />
            <Route path="/arrears" element={<ArrearsPage />} />
            <Route path="/transactions" element={<TransactionsPage />} />
            <Route path="/inactive" element={<InactivePage />} />
            <Route path="/cod" element={<CodPage />} />
            <Route path="/payments" element={<PaymentsPage />} />
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/companies/:name" element={<CompanyPage />} />
            <Route path="/corrections" element={<CorrectionsPage />} />
            <Route path="/ev-rent" element={<EvRentPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/requests" element={<RequestsPage />} />
            <Route path="/users" element={<UsersPage />} />
            <Route path="/system" element={<SystemPage />} />
            <Route path="/raft"  element={<RaftPage />} />
            <Route path="/blive" element={<BlivePage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Route>
      </Routes>
    </Suspense>
  )
}
