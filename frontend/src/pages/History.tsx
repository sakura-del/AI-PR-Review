import { useEffect, useState } from 'react'
import { api, AnalysisRecord } from '../api'

export function History() {
  const [records, setRecords] = useState<AnalysisRecord[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.history(100)
      .then(setRecords)
      .catch((e) => setError(e.message))
  }, [])

  return (
    <div>
      <h1>Review History</h1>
      {error && <div className="error-banner">{error}</div>}
      {records.length === 0 ? (
        <div className="empty-state">暂无审查记录</div>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>PR</th>
              <th>Findings</th>
              <th>🔴</th>
              <th>🟡</th>
              <th>🟢</th>
              <th>Duration</th>
            </tr>
          </thead>
          <tbody>
            {records.map((r, i) => (
              <tr key={i}>
                <td>{formatTime(r.timestamp)}</td>
                <td>
                  <a href={r.pr_url} target="_blank">
                    {(r.pr_title || '').slice(0, 60)}
                  </a>
                </td>
                <td className="num">{r.findings_count || 0}</td>
                <td className="num red">{r.high_severity_count || '-'}</td>
                <td className="num amber">{r.medium_severity_count || '-'}</td>
                <td className="num green">{r.low_severity_count || '-'}</td>
                <td className="num">{r.duration_seconds ? `${r.duration_seconds}s` : '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function formatTime(iso: string) {
  if (!iso) return '-'
  return iso.slice(0, 19).replace('T', ' ')
}