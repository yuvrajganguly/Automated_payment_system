import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from './AuthContext'
import { Spinner } from '../components/Spinner'
import { canVisit, homeFor } from '../components/workspaces'

export function ProtectedRoute() {
  const { user, loading } = useAuth()
  const { pathname } = useLocation()
  // Wait for the initial /auth/me probe before deciding — avoids redirecting a
  // logged-in user to /login on a hard refresh while the cookie is verified.
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Spinner />
      </div>
    )
  }
  if (!user) return <Navigate to="/login" replace />
  // A recruiter's app is riders + fleet; the money side does not exist for them.
  if (!canVisit(user.role, pathname)) return <Navigate to={homeFor(user.role)} replace />
  return <Outlet />
}
