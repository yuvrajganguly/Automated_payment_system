import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from './AuthContext'
import { Spinner } from '../components/Spinner'

export function ProtectedRoute() {
  const { user, loading } = useAuth()
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
  return <Outlet />
}
