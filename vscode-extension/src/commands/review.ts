/**
 * Review PR 命令：提交异步审查任务，轮询结果，Markdown Webview 展示
 */
import * as vscode from 'vscode';
import { ApiClient, ApiError, Job } from '../api/client';

const POLL_INTERVAL_MS = 3000;
const POLL_TIMEOUT_MS = 5 * 60 * 1000; // 5 min

export async function reviewPRCommand(
  api: ApiClient,
  output: vscode.OutputChannel
): Promise<void> {
  // 1. 收 PR URL
  const prUrl = await vscode.window.showInputBox({
    prompt: 'GitHub PR URL',
    placeHolder: 'https://github.com/owner/repo/pull/123',
    ignoreFocusOut: true,
  });
  if (!prUrl) return;

  // 2. 提交
  let job: { job_id: string };
  try {
    job = await api.submitJob(prUrl);
  } catch (e) {
    const err = e as ApiError;
    vscode.window.showErrorMessage(`提交失败：${err.message}`);
    return;
  }
  output.appendLine(`[INFO] Job ${job.job_id} submitted`);

  // 3. 显示 loading + 轮询
  await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: `AI PR Review 审查中（${job.job_id.slice(0, 8)}）`,
      cancellable: true,
    },
    async (progress) => {
      const start = Date.now();
      while (Date.now() - start < POLL_TIMEOUT_MS) {
        await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
        try {
          const j: Job = await api.getJob(job.job_id);
          if (j.status === 'succeeded') {
            await showResultWebview(prUrl, j);
            return;
          }
          if (j.status === 'failed') {
            vscode.window.showErrorMessage(
              `审查失败：${j.error || '未知错误'}`
            );
            return;
          }
          if (j.status === 'cancelled') {
            vscode.window.showWarningMessage('审查已取消');
            return;
          }
          // pending / running：继续轮询
          progress.report({ message: `状态：${j.status}` });
        } catch (e) {
          output.appendLine(`[WARN] poll error: ${(e as Error).message}`);
        }
      }
      vscode.window.showWarningMessage('审查超时（5 分钟）');
    }
  );
}

async function showResultWebview(prUrl: string, job: Job): Promise<void> {
  const panel = vscode.window.createWebviewPanel(
    'ai-pr-review.result',
    `Review ${prUrl.split('/').pop()}`,
    vscode.ViewColumn.Beside,
    { enableScripts: true }
  );
  panel.webview.html = renderMarkdown(prUrl, job);
}

function renderMarkdown(prUrl: string, job: Job): string {
  const result = job.result;
  if (!result) {
    return `<html><body><h1>No result</h1></body></html>`;
  }
  return `<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    body { font-family: -apple-system, sans-serif; padding: 20px; line-height: 1.5; }
    h1 { color: #2563eb; }
    h2 { color: #1e40af; margin-top: 24px; }
    .summary { background: #f1f5f9; padding: 12px 16px; border-radius: 6px; }
    .stat { display: inline-block; margin-right: 16px; font-weight: 600; }
    .stat-num { color: #2563eb; font-size: 18px; }
    .meta { color: #64748b; font-size: 12px; margin-top: 8px; }
  </style>
</head>
<body>
  <h1>🤖 AI PR Review</h1>
  <p><a href="${prUrl}">${prUrl}</a></p>
  <p class="meta">Job ${job.id} · ${job.started_at || ''} → ${job.finished_at || ''}</p>

  <h2>📋 变更总结</h2>
  <div class="summary">
    <p><strong>意图</strong>：${result.summary.intent}</p>
    <p><strong>范围</strong>：${result.summary.scope}</p>
    <p><strong>关键修改</strong>：</p>
    <ul>
      ${(result.summary.key_changes || []).map((c) => `<li>${c}</li>`).join('')}
    </ul>
  </div>

  <h2>📊 统计</h2>
  <p>
    <span class="stat">Findings: <span class="stat-num">${result.findings_count}</span></span>
    <span class="stat">Suggestions: <span class="stat-num">${result.suggestions_count}</span></span>
  </p>

  ${result.findings ? `<h2>⚠️ Findings</h2>${renderFindings(result.findings)}` : ''}
  ${result.suggestions ? `<h2>💡 Suggestions</h2>${renderSuggestions(result.suggestions)}` : ''}
</body>
</html>`;
}

function renderFindings(findings: Array<{ file: string; line: number; title: string; description: string; suggestion: string; severity: string }>): string {
  return findings
    .map(
      (f) => `<div style="border-left: 3px solid #f59e0b; padding: 8px 12px; margin: 8px 0; background: #fffbeb;">
  <strong>[${f.severity}] ${f.title}</strong> — <code>${f.file}:${f.line}</code>
  <p>${f.description}</p>
  <p><em>建议：</em>${f.suggestion}</p>
</div>`
    )
    .join('');
}

function renderSuggestions(suggestions: Array<{ description: string }>): string {
  return '<ul>' + suggestions.map((s) => `<li>${s.description}</li>`).join('') + '</ul>';
}

export async function showJobCommand(api: ApiClient, _output: vscode.OutputChannel): Promise<void> {
  const jobId = await vscode.window.showInputBox({ prompt: 'Job ID' });
  if (!jobId) return;
  try {
    const j = await api.getJob(jobId);
    await showResultWebview(`(job ${j.id})`, j);
  } catch (e) {
    vscode.window.showErrorMessage(`查询失败：${(e as ApiError).message}`);
  }
}