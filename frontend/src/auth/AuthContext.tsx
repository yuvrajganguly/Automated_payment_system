import React, { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, configureClient } from '../api/client'
import type { User } from '../api/types'

interface AuthState {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthState | undefined>(undefined)
// Only non-sensitive display info (email/role) is cached here. The JWT lives in
// an httpOnly cookie the browser sends automatically — never in JS storage.
const USER_KEY = 'payout_user'

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate()
  const [user, setUser] = useState<User | null>(() => {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? (JSON.parse(raw) as User) : null
  })
  const [loading, setLoading] = useState(true)

  function clearSession() {
    setUser(null)
    localStorage.removeItem(USER_KEY)
  }

  useEffect(() => {
    configureClient({
      onUnauthorized: () => {
        clearSession()
        navigate('/login', { replace: true })
      },
    })
  }, [navigate])

  // On load, confirm the cookie session with the server (rehydrate or clear).
  // Uses a raw fetch so a 401 here doesn't trigger the global redirect — public
  // pages (login, forgot-password) must stay reachable when logged out.
  useEffect(() => {
    let active = true
    fetch('/api/auth/me', { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error('unauthenticated'))))
      .then((u: User) => {
        if (!active) return
        setUser(u)
        localStorage.setItem(USER_KEY, JSON.stringify(u))
      })
      .catch(() => {
        if (active) clearSession()
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

  const login = async (email: string, password: string) => {
    const r = await api.loginForm(email, password)
    const u: User = { email: r.email, role: r.role }
    setUser(u)
    localStorage.setItem(USER_KEY, JSON.stringify(u))
  }

  const logout = () => {
    api.logout().catch(() => {})
    clearSession()
    navigate('/login', { replace: true })
  }

  const value = useMemo(() => ({ user, loading, login, logout }), [user, loading])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
