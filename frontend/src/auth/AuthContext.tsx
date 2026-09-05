import React, { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, configureClient } from '../api/client'
import type { TokenResponse, User } from '../api/types'

interface AuthState {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  /** Passwordless: the 6-digit code sent to the phone on WhatsApp. */
  loginWithOtp: (phone: string, otp: string) => Promise<void>
  logout: () => void
  /** Re-read /auth/me (after a profile change such as the phone number). */
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthState | undefined>(undefined)
// Only non-sensitive display info (email/role) is cached here. The JWT lives in
// an httpOnly cookie the browser sends automatically — never in JS storage.
const USER_KEY = 'payout_user'

// localStorage throws in some private/embedded contexts; treat it as optional.
const safeGet = (k: string) => { try { return localStorage.getItem(k) } catch { return null } }
const safeSet = (k: string, v: string) => { try { localStorage.setItem(k, v) } catch { /* ignore */ } }
const safeRemove = (k: string) => { try { localStorage.removeItem(k) } catch { /* ignore */ } }

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate()
  const [user, setUser] = useState<User | null>(() => {
    // A corrupt/legacy value here used to throw inside the initializer and
    // blank the whole app before first render.
    try {
      const raw = safeGet(USER_KEY)
      const parsed = raw ? (JSON.parse(raw) as Partial<User>) : null
      return parsed && typeof parsed.email === 'string' && typeof parsed.role === 'string'
        ? (parsed as User)
        : null
    } catch {
      return null
    }
  })
  const [loading, setLoading] = useState(true)

  function clearSession() {
    setUser(null)
    safeRemove(USER_KEY)
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
  // silent401: a 401 here must not trigger the global redirect — public pages
  // (login, forgot-password) must stay reachable when logged out.
  useEffect(() => {
    let active = true
    api.get<User>('/auth/me', { silent401: true })
      .then((u: User) => {
        if (!active) return
        setUser(u)
        safeSet(USER_KEY, JSON.stringify(u))
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
    safeSet(USER_KEY, JSON.stringify(u))
  }

  const loginWithOtp = async (phone: string, otp: string) => {
    const r = await api.post<TokenResponse>('/auth/otp/login', { phone, otp }, { silent401: true })
    const u: User = { email: r.email, role: r.role }
    setUser(u)
    safeSet(USER_KEY, JSON.stringify(u))
  }

  const logout = () => {
    api.logout().catch(() => {})
    clearSession()
    navigate('/login', { replace: true })
  }

  const refresh = async () => {
    const u = await api.get<User>('/auth/me', { silent401: true })
    setUser(u)
    safeSet(USER_KEY, JSON.stringify(u))
  }

  const value = useMemo(() => ({ user, loading, login, loginWithOtp, logout, refresh }), [user, loading])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
