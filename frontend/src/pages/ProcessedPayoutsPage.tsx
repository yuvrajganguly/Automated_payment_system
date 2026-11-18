import { Navigate } from 'react-router-dom'
import type { ProcessedPayout } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { PayoutDownload } from '../components/PayoutDownload'
import { Spinner } from '../components/Spinner'
import { useApi } from '../hooks/useApi'
import { useUrlString } from '../state/useUrlState'

export function ProcessedPayoutsPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin' || user?.role === 'creator'
  const { data, error, loading, reload } = useApi<{ runs: ProcessedPayout[] }>(isAdmin ? '/cycles/history' : null)
  const [company, setCompany] = useUrlString('company')

  if (!isAdmin) return <Navigate to="/" replace />
  const runs = data?.runs ?? []
  const companies = Array.from(new Set([...runs.map((r) => r.company), ...(company ? [company] : [])])).sort()
  const visible = company ? runs.filter((r) => r.company === company) : runs

  return (
    <div className="max-w-6xl mx-auto">
      <h1 className="page-title mb-1">Processed payouts</h1>
      <p className="text-sm text-slate-500 mb-5">Download a workbook from an earlier payout. Downloading leaves the ledger unchanged.</p>
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <label className="text-sm">Company{' '}
          <select value={company} onChange={(e) => setCompany(e.target.value)} className="border rounded px-2 py-1">
            <option value="">All companies</option>
            {companies.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <button type="button" onClick={reload} disabled={loading} className="text-sm text-brand underline disabled:opacity-50">Refresh</button>
      </div>
      {error && <p role="alert" className="text-red-400 text-sm mb-3">{error}</p>}
      {loading && !data ? <Spinner label="Loading processed payouts…" /> : data && (
        visible.length === 0 ? <p className="panel p-4 text-sm text-slate-500">No processed payouts{company ? ` for ${company}` : ''}.</p> : (
          <div className="panel overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-slate-500"><tr>
                <th className="px-4 py-2">Company</th><th className="px-4 py-2">Payout</th>
                <th className="px-4 py-2">Processed</th><th className="px-4 py-2">Workbook</th>
              </tr></thead>
              <tbody>
                {visible.map((r) => (
                  <tr key={`${r.kind}/${r.id}`} className="border-t border-edge-soft align-top">
                    <td className="px-4 py-3 font-medium">{r.company}</td>
                    <td className="px-4 py-3">
                      {r.kind === 'cycle' ? `${r.cycle_start} → ${r.cycle_end}` : `Ad-hoc #${r.id} · ${r.cycle_end}`}
                      {r.label && <div className="text-xs text-slate-500">{r.label}</div>}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">{r.processed_at?.replace('T', ' ').slice(0, 16) || '—'}</td>
                    <td className="px-4 py-3">
                      <PayoutDownload run={r} label={r.report === 'original' ? 'Download workbook' : r.report === 'ledger' ? 'Download ledger report' : 'Download summary'} />
                      {r.report !== 'original' && <p className="mt-1 text-xs text-slate-500">
                        {r.report === 'ledger' ? 'Rebuilt from saved entries. The original workbook was not archived.' : 'Recorded totals only. The original workbook was not archived.'}
                      </p>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}
    </div>
  )
}
