/**
 * "Export to Excel" button that hits an API endpoint returning a styled .xlsx
 * and triggers a browser download.
 *
 * Goes through `api.download` so the auth cookie, the 401 -> login redirect
 * and error parsing behave like every other call. The server sends a
 * Content-Disposition with a timestamped filename; `name` is the fallback.
 */
import { useState } from 'react'
import { api, saveBlob } from '../api/client'

interface Props {
  /** API path under /api — e.g. "/arrears/export". */
  path: string
  /** Fallback filename when the response doesn't supply one. */
  name: string
  /** Optional query string (e.g. "active=true"); leading "?" optional. */
  query?: string
  /** When set, only these row ids are exported (POSTed as the filtered scope). */
  ids?: (string | number)[]
  className?: string
}

export function ExportButton({ path, name, query, ids, className = '' }: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function go() {
    setBusy(true)
    try {
      const q = query ? (query.startsWith('?') ? query : '?' + query) : ''
      // Server-provided filename (Content-Disposition) wins over `name`.
      const dl = await api.download(path + q, {
        fallbackName: name,
        ...(ids !== undefined ? { json: { ids } } : {}),
      })
      saveBlob(dl)
    } catch (e) {
      setError('Export failed: ' + (e instanceof Error ? e.message : 'unknown'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <span className="inline-flex items-center gap-2">
      <button onClick={go} disabled={busy}
              className={
                'text-sm bg-emerald-600 hover:bg-emerald-500 text-white ' +
                'px-3 py-1.5 rounded inline-flex items-center gap-1 ' +
                'disabled:opacity-50 ' + className
              }>
        <span aria-hidden="true">⬇</span>
        {busy ? 'Exporting…' : 'Export to Excel'}
      </button>
      {error && <span role="alert" className="text-xs text-rose-400">{error}</span>}
    </span>
  )
}
