import { Navigate, Route, Routes } from 'react-router-dom'
import { ProtectedRoute } from './auth/ProtectedRoute'
import { Layout } from './components/Layout'
import { ArrearsPage } from './pages/ArrearsPage'
import { EvProfilePage } from './pages/EvProfilePage'
import { EVsPage } from './pages/EVsPage'
import { ForgotPasswordPage } from './pages/ForgotPasswordPage'
import { LoginPage } from './pages/LoginPage'
import { PersonPage } from './pages/PersonPage'
import { ProcessPayoutPage } from './pages/ProcessPayoutPage'
import { RidersPage } from './pages/RidersPage'
import { SettingsPage } from './pages/SettingsPage'
import { UsersPage } from './pages/UsersPage'
import { CodPage } from './pages/CodPage'
import { DashboardPage } from './pages/DashboardPage'
import { PaymentsPage } from './pages/PaymentsPage'
import { EvRentPage } from './pages/EvRentPage'
import { InactivePage } from './pages/InactivePage'
import { TransactionsPage } from './pages/TransactionsPage'
import { SystemPage } from './pages/SystemPage'
import { RaftPage } from './pages/RaftPage'
import { BlivePage } from './pages/BlivePage'

export default function App() {
  return (
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
          <Route path="/ev-rent" element={<EvRentPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/users" element={<UsersPage />} />
          <Route path="/system" element={<SystemPage />} />
          <Route path="/raft"  element={<RaftPage />} />
          <Route path="/blive" element={<BlivePage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Route>
    </Routes>
  )
}
