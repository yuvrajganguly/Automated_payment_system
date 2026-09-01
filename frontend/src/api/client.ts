import type { TokenResponse } from './types'

const BASE = '/api'

let onUnauthorized: () => void = () => {}

export function configureClient(opts: { onUnauthorized: () => void }) {
  onUnauthorized = opts.onUnauthorized
}

/** Error thrown for any non-2xx response. `status` lets callers branch. */
export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function errorDetail(res: Response): Promise<string> {
  try {
    const body = await res.json()
    if (typeof body?.detail === 'string') return body.detail
    if (Array.isArray(body?.detail)) {
      // FastAPI validation errors: [{loc, msg, ...}]
      return body.detail.map((d: { msg?: string }) => d.msg ?? '').filter(Boolean).join('; ')
    }
  } catch {
    // not JSON
  }
  return res.statusText || `HTTP ${res.status}`
}

export interface RequestOptions extends RequestInit {
  /** Query-string parameters; undefined / null / '' values are dropped. */
  query?: Record<string, string | number | boolean | undefined | null>
  /** Skip the global 401 -> login redirect (used by the session probe). */
  silent401?: boolean
}

function withQuery(path: string, query?: RequestOptions['query']): string {
  if (!query) return path
  const params = new URLSearchParams()
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === '') continue
    params.set(k, String(v))
  }
  const qs = params.toString()
  return qs ? path + (path.includes('?') ? '&' : '?') + qs : path
}

async function send(path: string, { query, silent401, ...init }: RequestOptions): Promise<Response> {
  // Auth travels in an httpOnly cookie; `credentials: 'include'` sends it on
  // every same-origin request. The JWT is never exposed to JS (XSS-safe).
  const res = await fetch(BASE + withQuery(path, query), { ...init, credentials: 'include' })
  if (res.status === 401 && !silent401) {
    onUnauthorized()
    throw new ApiError(401, 'Session expired - please sign in again')
  }
  if (!res.ok) throw new ApiError(res.status, await errorDetail(res))
  return res
}

async function request<T>(path: string, init: RequestOptions = {}): Promise<T> {
  const res = await send(path, init)
  if (res.status === 204) return undefined as T
  return res.json()
}

const json = (body: unknown): Pick<RequestInit, 'headers' | 'body'> => ({
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export interface Download {
  blob: Blob
  filename: string
}

/** Pull the filename out of a Content-Disposition header, if present. */
function filenameFrom(res: Response, fallback: string): string {
  const cd = res.headers.get('content-disposition') ?? ''
  const m = cd.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i)
  return m?.[1] ? decodeURIComponent(m[1]) : fallback
}

/** Trigger a browser download for a blob. */
export function saveBlob({ blob, filename }: Download): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export const api = {
  get: <T,>(path: string, opts: RequestOptions = {}) => request<T>(path, opts),
  post: <T,>(path: string, body?: unknown, opts: RequestOptions = {}) =>
    request<T>(path, { method: 'POST', ...(body === undefined ? {} : json(body)), ...opts }),
  patch: <T,>(path: string, body?: unknown, opts: RequestOptions = {}) =>
    request<T>(path, { method: 'PATCH', ...(body === undefined ? {} : json(body)), ...opts }),
  put: <T,>(path: string, body?: unknown, opts: RequestOptions = {}) =>
    request<T>(path, { method: 'PUT', ...(body === undefined ? {} : json(body)), ...opts }),
  delete: <T,>(path: string, opts: RequestOptions = {}) =>
    request<T>(path, { method: 'DELETE', ...opts }),
  postForm: <T,>(path: string, form: FormData, opts: RequestOptions = {}) =>
    request<T>(path, { method: 'POST', body: form, ...opts }),

  /**
   * Fetch a binary (xlsx) response. Goes through the same 401 handling and
   * error parsing as every other call — the raw `fetch` copies of this in
   * four pages did not.
   */
  download: async (
    path: string,
    {
      fallbackName = 'download.xlsx',
      json: jsonBody,
      ...opts
    }: Omit<RequestOptions, 'body'> & { fallbackName?: string; json?: unknown } = {},
  ): Promise<Download> => {
    // `json` (an object) is POSTed; without it the download is a GET.
    const init: RequestOptions =
      jsonBody === undefined ? opts : { method: 'POST', ...json(jsonBody), ...opts }
    const res = await send(path, init)
    return { blob: await res.blob(), filename: filenameFrom(res, fallbackName) }
  },

  loginForm: async (email: string, password: string): Promise<TokenResponse> => {
    const form = new URLSearchParams()
    form.set('username', email)
    form.set('password', password)
    const res = await fetch(BASE + '/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: form.toString(),
      credentials: 'include',
    })
    if (!res.ok) throw new ApiError(res.status, await errorDetail(res))
    return res.json()
  },
  logout: () => request<{ ok: boolean }>('/auth/logout', { method: 'POST' }),
}
