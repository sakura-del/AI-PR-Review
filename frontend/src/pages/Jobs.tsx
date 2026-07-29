import { useEffect, useState } from 'react'
import { api, Job } from '../api'

const REFRESH_MS = 3000

export function Jobs() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true
    async function tick() {
      try {
        const data = await api.jobs()
        if (active) {
          setJobs(data)
          setError(null)
        }
      } catch (e: any) {
        if (active) setError(e.message)
      } finally {
        if (active) setLoading(false)
      }
    }
    tick()
    const timer = setInterval(tick, REFRESH_MS)
    return () => { active = false; clearInterval(timer) }
  }, [])

  const statusBadge = (s: string) => {
    const map: Record<string, string> = {
      pending: '🟡 pending',
      running: '🔵 running',
      succeeded: '🟢 succeeded',
      failed: '🔴 failed',
      cancelled: '⚪ cancelled',
    }
    return <span className={`status-badge status-${s}`}>{map[s] || s}</span>
  }

  return (
    <div>
      <h1>Jobs <small className="muted">(auto-refresh {REFRESH_MS / 1000}s)</small></h1>
      {error && <div className="error-banner">{error}</div>}

      {loading && jobs.length === 0 ? (
        <div className="empty-state">加载中…</div>
      ) : jobs.length === 0 ? (
        <div className="empty-state">暂无任务</div>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>PR</th>
              <th>Status</th>
              <th>Created</th>
              <th>Finished</th>
              <th>Error</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((j) => (
              <tr key={j.id}>
                <td><code title={j.id}>{j.id.slice(0, 8)}</code></td>
                <td><a href={j.pr_url} target="_blank">{j.pr_url}</a></td>
                <td>{statusBadge(j.status)}</td>
                <td>{formatTime(j.created_at)}</td>
                <td>{j.finished_at ? formatTime(j.finished_at) : '-'}</td>
                <td className="job-error" title={j.error || ''}>
                  {j.error ? j.error.slice(0, 50) : ''}
                </td>
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