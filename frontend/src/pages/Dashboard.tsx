import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, AnalysisRecord, Stats } from '../api'

export function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [recent, setRecent] = useState<AnalysisRecord[]>([])
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [prUrl, setPrUrl] = useState('')
  const navigate = useNavigate()

  useEffect(() => {
    refresh()
  }, [])

  async function refresh() {
    setError(null)
    try {
      const [s, h] = await Promise.all([api.stats(), api.history(10)])
      setStats(s)
      setRecent(h)
    } catch (e: any) {
      setError(e.message)
    }
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!prUrl.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      await api.submitJob(prUrl.trim())
      setPrUrl('')
      navigate('/jobs')
    } catch (e: any) {
      setError(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div>
      {error && <div className="error-banner">{error}</div>}

      <h1>Dashboard</h1>

      {stats ? (
        <div className="stats-grid">
          <StatCard label="Total reviews" value={stats.total} />
          <StatCard label="🔴 HIGH" value={stats.high} color="red" />
          <StatCard label="🟡 MEDIUM" value={stats.medium} color="amber" />
          <StatCard label="🟢 LOW" value={stats.low} color="green" />
          <StatCard label="Avg duration (s)" value={stats.avg_duration.toFixed(2)} />
        </div>
      ) : (
        <div className="empty-state">Loading stats…</div>
      )}

      <h2>Submit a PR</h2>
      <form onSubmit={onSubmit} className="submit-form">
        <input
          type="url"
          value={prUrl}
          onChange={(e) => setPrUrl(e.target.value)}
          placeholder="https://github.com/owner/repo/pull/123"
          required
        />
        <button type="submit" disabled={submitting}>
          {submitting ? '提交中…' : 'Submit Review'}
        </button>
      </form>

      <h2>Recent reviews</h2>
      {recent.length === 0 ? (
        <div className="empty-state">暂无审查记录。提交一个 PR URL 试试 →</div>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>PR</th>
              <th>🔴</th>
              <th>🟡</th>
              <th>🟢</th>
              <th>Duration</th>
            </tr>
          </thead>
          <tbody>
            {recent.map((r, i) => (
              <tr key={i}>
                <td>{formatTime(r.timestamp)}</td>
                <td>
                  <a href={r.pr_url} target="_blank">
                    {(r.pr_title || '').slice(0, 60)}
                  </a>
                </td>
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

function StatCard({ label, value, color }: { label: string; value: string | number; color?: 'red' | 'amber' | 'green' }) {
  return (
    <div className={`stat-card ${color ? 'accent-' + color : ''}`}>
      <div className="label">{label}</div>
      <div className="value">{value}</div>
    </div>
  )
}

function formatTime(iso: string) {
  if (!iso) return '-'
  return iso.slice(0, 19).replace('T', ' ')
}