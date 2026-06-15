import React, { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, configureClient } from '../api/client'
import type { User } from '../api/types'

interface AuthState {
  user: User | null
  token: string | null
  login: (email: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthState | undefined>(undefined)
const TOKEN_KEY = 'payout_token'
const USER_KEY = 'payout_user'

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate()
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_KEY))
  const [user, setUser] = useState<User | null>(() => {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? (JSON.parse(raw) as User) : null
  })

  useEffect(() => {
    configureClient({
      getToken: () => token,
      onUnauthorized: () => {
        setToken(null)
        setUser(null)
        localStorage.removeItem(TOKEN_KEY)
        localStorage.removeItem(USER_KEY)
        navigate('/login', { replace: true })
      },
    })
  }, [token, navigate])

  const login = async (email: string, password: string) => {
    const r = await api.loginForm(email, password)
    const u: User = { email: r.email, role: r.role }
    setToken(r.access_token)
    setUser(u)
    localStorage.setItem(TOKEN_KEY, r.access_token)
    localStorage.setItem(USER_KEY, JSON.stringify(u))
  }

  const logout = () => {
    setToken(null)
    setUser(null)
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
    navigate('/login', { replace: true })
  }

  const value = useMemo(() => ({ user, token, login, logout }), [user, token])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
