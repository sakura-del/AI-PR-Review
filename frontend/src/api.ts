// AI PR Review API 客户端

const API_BASE = ''  // same origin (通过 Vite proxy 或 FastAPI 静态服务)

export interface User {
  authenticated: boolean
  user_id?: string
  github_login?: string
  github_id?: number
}

export interface Stats {
  total: number
  high: number
  medium: number
  low: number
  avg_duration: number
}

export interface AnalysisRecord {
  pr_url: string
  pr_title: string
  timestamp: string
  findings_count: number
  high_severity_count: number
  medium_severity_count: number
  low_severity_count: number
  suggestions_count: number
  model: string
  duration_seconds: number
  head_sha: string
  base_sha: string
  is_incremental: boolean
  user_id: string
}

export interface Job {
  id: string
  pr_url: string
  status: 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled'
  progress: string
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  result: any | null
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const resp = await fetch(API_BASE + path, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!resp.ok) {
    let detail = ''
    try { detail = (await resp.json()).detail || '' } catch {}
    throw new Error(`${resp.status} ${resp.statusText}${detail ? ': ' + detail : ''}`)
  }
  return resp.status === 204 ? null as unknown as T : resp.json()
}

export const api = {
  me: () => request<User>('/auth/me'),
  stats: () => request<Stats>('/api/stats'),
  history: (limit = 20) => request<AnalysisRecord[]>(`/api/history?limit=${limit}`),
  jobs: () => request<Job[]>('/api/jobs'),
  submitJob: (prUrl: string) =>
    request<Job>('/api/jobs', {
      method: 'POST',
      body: JSON.stringify({ pr_url: prUrl }),
    }),
  health: () => request<{ status: string; version: string }>('/api/health'),
}