/**
 * Dashboard 命令：Sidebar Webview 显示统计 + 提交 + Jobs + History
 */
import * as vscode from 'vscode';
import { ApiClient, Stats, Job } from '../api/client';

export async function showDashboardCommand(
  _context: vscode.ExtensionContext,
  api: ApiClient,
  _output: vscode.OutputChannel
): Promise<void> {
  const panel = vscode.window.createWebviewPanel(
    'ai-pr-review.dashboard',
    'AI PR Review Dashboard',
    vscode.ViewColumn.One,
    { enableScripts: true, retainContextWhenHidden: true }
  );

  // 初始渲染
  panel.webview.html = renderHtml(null, [], null);

  // 加载数据
  await refresh(panel, api);

  // 定时刷新
  const interval = setInterval(() => refresh(panel, api), 5000);
  panel.onDidDispose(() => clearInterval(interval));
}

async function refresh(
  panel: vscode.WebviewPanel,
  api: ApiClient
): Promise<void> {
  try {
    const [stats, jobs] = await Promise.all([api.stats(), api.listJobs(10)]);
    panel.webview.html = renderHtml(stats, jobs, null);
  } catch (e) {
    panel.webview.html = renderHtml(null, [], (e as Error).message);
  }
}

function renderHtml(
  stats: Stats | null,
  jobs: Job[] | null,
  err: string | null
): string {
  if (err) {
    return `<html><body style="font-family:sans-serif;padding:20px">
      <h1>⚠️ 连接失败</h1>
      <pre style="background:#fee;padding:12px">${err}</pre>
      <p>检查设置 <code>ai-pr-review.apiBaseUrl</code> 是否正确，web 服务是否启动。</p>
    </body></html>`;
  }
  return `<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    body { font-family: -apple-system, sans-serif; padding: 20px; line-height: 1.5; }
    h1 { color: #2563eb; }
    .stats { display: flex; gap: 16px; margin: 16px 0; }
    .stat-card { background: #f1f5f9; padding: 12px 16px; border-radius: 6px; min-width: 120px; }
    .stat-num { font-size: 24px; font-weight: 600; color: #2563eb; }
    .stat-label { font-size: 12px; color: #64748b; }
    table { width: 100%; border-collapse: collapse; margin-top: 12px; }
    th, td { padding: 8px; text-align: left; border-bottom: 1px solid #e2e8f0; font-size: 13px; }
    th { background: #f8fafc; color: #475569; }
    .status-pending { color: #d97706; }
    .status-running { color: #2563eb; }
    .status-succeeded { color: #16a34a; }
    .status-failed { color: #dc2626; }
  </style>
</head>
<body>
  <h1>📊 Dashboard</h1>
  ${stats ? `
  <div class="stats">
    <div class="stat-card"><div class="stat-label">Total</div><div class="stat-num">${stats.total}</div></div>
    <div class="stat-card"><div class="stat-label">🔴 HIGH</div><div class="stat-num">${stats.high}</div></div>
    <div class="stat-card"><div class="stat-label">🟡 MED</div><div class="stat-num">${stats.medium}</div></div>
    <div class="stat-card"><div class="stat-label">🟢 LOW</div><div class="stat-num">${stats.low}</div></div>
    <div class="stat-card"><div class="stat-label">Avg (s)</div><div class="stat-num">${stats.avg_duration.toFixed(2)}</div></div>
  </div>` : '<p>Loading stats...</p>'}

  <h2>Jobs (auto-refresh 5s)</h2>
  ${jobs && jobs.length > 0 ? `
  <table>
    <thead><tr><th>ID</th><th>PR</th><th>Status</th><th>Created</th></tr></thead>
    <tbody>
      ${jobs.map(j => `<tr>
        <td><code>${j.id.slice(0, 8)}</code></td>
        <td><a href="${j.pr_url}">${j.pr_url.split('/').slice(-1)[0]}</a></td>
        <td class="status-${j.status}">${j.status}</td>
        <td>${j.created_at.slice(11, 19)}</td>
      </tr>`).join('')}
    </tbody>
  </table>` : '<p>暂无任务</p>'}
</body>
</html>`;
}