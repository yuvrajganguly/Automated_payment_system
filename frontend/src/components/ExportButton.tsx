/**
 * "Export to Excel" button that hits an API endpoint returning a styled .xlsx
 * and triggers a browser download.
 *
 * Uses fetch + Blob (instead of an <a download> tag) so we can include the
 * Authorization header that the API requires. The server already sends a
 * proper Content-Disposition with a timestamped filename, but we use the
 * `name` prop as a fallback when the response header gets stripped by some
 * older browsers.
 */
import { useState } from 'react'

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

  async function go() {
    setBusy(true)
    try {
      const q = query ? (query.startsWith('?') ? query : '?' + query) : ''
      const init: RequestInit = ids !== undefined
        ? { method: 'POST', credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ids }) }
        : { credentials: 'include' }
      const r = await fetch('/api' + path + q, init)
      if (!r.ok) {
        alert('Export failed: ' + r.status + ' ' + r.statusText)
        return
      }
      // Prefer the server-provided filename from Content-Disposition.
      let filename = name
      const cd = r.headers.get('content-disposition') ?? ''
      const m = cd.match(/filename="?([^"]+)"?/i)
      if (m) filename = m[1]
      const blob = await r.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = filename
      document.body.appendChild(a); a.click(); a.remove()
      URL.revokeObjectURL(url)
    } catch (e) {
      alert('Export failed: ' + (e instanceof Error ? e.message : 'unknown'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <button onClick={go} disabled={busy}
            className={
              'text-sm bg-emerald-600 hover:bg-emerald-700 text-white ' +
              'px-3 py-1.5 rounded inline-flex items-center gap-1 ' +
              'disabled:opacity-50 ' + className
            }>
      <span>⬇</span>
      {busy ? 'Exporting…' : 'Export to Excel'}
    </button>
  )
}
