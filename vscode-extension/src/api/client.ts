/**
 * HTTP 客户端：调 v0.10 FastAPI Web 后端的 /api/* 端点
 */
import { URL } from 'url';

export interface ApiOptions {
  baseUrl: string;
  token?: string;
}

export class ApiError extends Error {
  constructor(public status: number, public body: string, message: string) {
    super(message);
  }
}

export class ApiClient {
  constructor(public options: ApiOptions) {}

  setBaseUrl(baseUrl: string) {
    this.options.baseUrl = baseUrl;
  }

  setToken(token: string | undefined) {
    this.options.token = token;
  }

  private async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const url = new URL(path, this.options.baseUrl);
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };
    if (this.options.token) {
      headers['Authorization'] = `token ${this.options.token}`;
    }

    // 跳过证书验证（开发自签证书友好）
    process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';

    const response = await fetch(url.toString(), {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });

    if (!response.ok) {
      const text = await response.text();
      throw new ApiError(response.status, text, `HTTP ${response.status} ${response.statusText}`);
    }
    if (response.status === 204) return null as T;
    return (await response.json()) as T;
  }

  // ===== Auth =====
  authMe = () => this.request<{ authenticated: boolean; user_id?: string; github_login?: string }>('GET', '/auth/me');
  authLoginUrl = () => `${this.options.baseUrl}/auth/login`;

  // ===== Stats / History / Jobs =====
  stats = () => this.request<Stats>('GET', '/api/stats');
  history = (limit = 20) => this.request<HistoryRecord[]>(
    'GET', `/api/history?limit=${limit}`
  );
  listJobs = (limit = 20) => this.request<Job[]>('GET', `/api/jobs?limit=${limit}`);
  getJob = (jobId: string) => this.request<Job>('GET', `/api/jobs/${jobId}`);

  submitJob = (prUrl: string) => this.request<SubmitJobResponse>('POST', '/api/jobs/', { pr_url: prUrl });
  health = () => this.request<HealthResponse>('GET', '/api/health');
}

export interface Stats {
  total: number;
  high: number;
  medium: number;
  low: number;
  avg_duration: number;
}

export interface HistoryRecord {
  pr_url: string;
  pr_title: string;
  timestamp: string;
  findings_count: number;
  high_severity_count: number;
  medium_severity_count: number;
  low_severity_count: number;
  suggestions_count: number;
  duration_seconds: number;
  head_sha: string;
  user_id: string;
  timestamp_display?: string;
}

export interface Job {
  id: string;
  pr_url: string;
  status: 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled';
  progress: string;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  result: JobResult | null;
}

export interface JobResult {
  summary: {
    intent: string;
    scope: string;
    key_changes: string[];
  };
  findings_count: number;
  suggestions_count: number;
  // 完整 finding 列表（v0.10 后端没暴露，留接口占位）
  findings?: Finding[];
  suggestions?: Suggestion[];
}

export interface Finding {
  type: string;
  severity: 'P0' | 'P1' | 'P2' | 'P3';
  confidence: number;
  expert: string;
  file: string;
  line: number;
  title: string;
  description: string;
  suggestion: string;
  code_snippet?: string;
}

export interface Suggestion {
  category: string;
  priority: string;
  description: string;
  example?: string;
}

export interface SubmitJobResponse {
  job_id: string;
  status: string;
  pr_url: string;
}

export interface HealthResponse {
  status: string;
  version: string;
  jobs: { pending: number; running: number };
  degradation_level: number;
}