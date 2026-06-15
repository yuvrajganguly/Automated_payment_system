import type { TokenResponse } from './types'

const BASE = '/api'
const TOKEN_KEY = 'payout_token'

let onUnauthorized: () => void = () => {}

export function configureClient(opts: {
  getToken?: () => string | null  // kept for backward compat; unused
  onUnauthorized: () => void
}) {
  onUnauthorized = opts.onUnauthorized
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  // Read token directly from localStorage so we always see the freshest value,
  // avoiding effect-ordering races between AuthContext and child page effects.
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const res = await fetch(BASE + path, { ...init, headers })
  if (res.status === 401) {
    onUnauthorized()
    throw new Error('Session expired - please sign in again')
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ?? detail
    } catch {
      // swallow body parse errors
    }
    throw new Error(detail)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

export const api = {
  get: <T,>(path: string) => request<T>(path),
  post: <T,>(path: string, body: unknown) =>
    request<T>(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  postForm: <T,>(path: string, form: FormData) =>
    request<T>(path, { method: 'POST', body: form }),
  loginForm: async (email: string, password: string): Promise<TokenResponse> => {
    const form = new URLSearchParams()
    form.set('username', email)
    form.set('password', password)
    const res = await fetch(BASE + '/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: form.toString(),
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(body.detail ?? 'Login failed')
    }
    return res.json()
  },
}
