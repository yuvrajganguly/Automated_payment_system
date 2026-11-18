import type { PayoutRunRef } from '../api/types'
import { ExportButton } from './ExportButton'

export function PayoutDownload({ run, label = 'Download workbook' }: { run: PayoutRunRef; label?: string }) {
  return <ExportButton path={`/cycles/history/${run.kind}/${run.id}/download`}
                       name={`payout_${run.kind}_${run.id}.xlsx`} label={label} />
}
