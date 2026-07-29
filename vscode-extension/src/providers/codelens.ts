/**
 * CodeLens Provider：在 PR 文件的 finding 行上方显示 AI 提示
 *
 * 工作流：
 * 1. 用户先跑 "AI PR Review: Review PR"，review_context 中缓存 job_id
 * 2. 编辑器打开 PR 涉及的文件 → activate() 提供 CodeLens
 * 3. 每个 finding 上方一个 lens，点击 → showFindingDetailCommand
 *
 * 缓存 key: pr_url + file_path → list of findings
 */
import * as vscode from 'vscode';
import { ApiClient, Finding, Job } from '../api/client';

interface ReviewContext {
  job_id: string;
  pr_url: string;
  files_with_findings: Map<string, Finding[]>;
}

let currentContext: ReviewContext | null = null;

export function setReviewContext(job: Job, prUrl: string): void {
  const files = new Map<string, Finding[]>();
  if (job.result?.findings) {
    for (const f of job.result.findings) {
      if (!files.has(f.file)) files.set(f.file, []);
      files.get(f.file)!.push(f);
    }
  }
  currentContext = { job_id: job.id, pr_url: prUrl, files_with_findings: files };
  // 触发 CodeLens 重新计算
  vscode.commands.executeCommand('vscode.executeCodeLensProvider');
  vscode.window.showInformationMessage(
    `CodeLens 已激活：${files.size} 个文件有发现`
  );
}

export function clearReviewContext(): void {
  currentContext = null;
  vscode.commands.executeCommand('vscode.executeCodeLensProvider');
}

export function getReviewContext(): ReviewContext | null {
  return currentContext;
}

export class AiPrReviewCodeLensProvider implements vscode.CodeLensProvider {
  constructor(_api: ApiClient) {}

  async provideCodeLenses(document: vscode.TextDocument): Promise<vscode.CodeLens[]> {
    if (!currentContext) return [];

    const filePath = this.normalizePath(document.uri.fsPath);
    const findings = currentContext.files_with_findings.get(filePath) || [];
    if (findings.length === 0) return [];

    const lenses: vscode.CodeLens[] = [];
    for (const f of findings) {
      const line = Math.max(0, f.line - 1);
      if (line >= document.lineCount) continue;
      const range = new vscode.Range(line, 0, line, 0);
      const lens = new vscode.CodeLens(range, {
        title: `🤖 AI: ${f.severity} ${f.title}`,
        command: 'ai-pr-review.showFindingDetail',
        arguments: [f],
        tooltip: `${f.description}\n\n建议：${f.suggestion}`,
      });
      lenses.push(lens);
    }
    return lenses;
  }

  private normalizePath(p: string): string {
    return p.split(/[\\/]/).pop() || p;
  }
}

export async function showFindingDetailCommand(
  finding: Finding,
  document?: vscode.TextDocument
): Promise<void> {
  const panel = vscode.window.createWebviewPanel(
    'ai-pr-review.finding',
    `Finding: ${finding.title}`,
    vscode.ViewColumn.Beside,
    { enableScripts: true }
  );

  // 找文件中的 old code 上下文
  let codeContext = finding.code_snippet || '';
  if (!codeContext && document) {
    const line = Math.max(0, finding.line - 1);
    if (line < document.lineCount) {
      const startLine = Math.max(0, line - 2);
      codeContext = [
        document.lineAt(startLine).text,
        document.lineAt(startLine + 1).text,
        document.lineAt(startLine + 2).text,
      ].join('\n');
    }
  }

  // v1.2 Apply Fix：new code 从 finding.suggestion 拿
  // （v1.3 可改成"调后端 /api/fixes/{finding_id} 拿真实 fix 代码"）
  const newCode = finding.suggestion;

  panel.webview.html = `
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="UTF-8">
      <style>
        body { font-family: -apple-system, sans-serif; padding: 20px; line-height: 1.5; }
        h1 { color: #2563eb; }
        h2 { color: #1e40af; margin-top: 24px; }
        pre { background: #f1f5f9; padding: 12px; border-radius: 6px; overflow-x: auto; font-size: 12px; }
        .severity { display: inline-block; padding: 4px 10px; border-radius: 4px; font-weight: 600; color: white; }
        .P0 { background: #dc2626; }
        .P1 { background: #ea580c; }
        .P2 { background: #f59e0b; }
        .P3 { background: #10b981; }
        .actions { margin: 24px 0; padding: 16px; background: #fef3c7; border-radius: 6px; }
        button { padding: 8px 16px; margin-right: 8px; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }
        .apply { background: #16a34a; color: white; }
        .apply:hover { background: #15803d; }
        .cancel { background: #e2e8f0; color: #1e293b; }
        .diff-old { background: #fee2e2; }
        .diff-new { background: #dcfce7; }
      </style>
    </head>
    <body>
      <h1>🤖 <span class="severity ${finding.severity}">${finding.severity}</span> ${finding.title}</h1>
      <p><code>${finding.file}:${finding.line}</code></p>

      <h2>📋 描述</h2>
      <p>${finding.description}</p>

      <h2>💡 建议</h2>
      <p>${finding.suggestion}</p>

      <h2>📝 当前代码</h2>
      <pre>${escapeHtml(codeContext)}</pre>

      <h2>✨ 修复后</h2>
      <pre class="diff-new">${escapeHtml(newCode)}</pre>

      <div class="actions">
        <strong>应用修复？</strong>
        <button class="apply" onclick="applyFix()">✓ Apply Fix</button>
        <button class="cancel" onclick="cancel()">✗ Cancel</button>
      </div>

      <script>
        const vscode = acquireVsCodeApi();
        function applyFix() {
          vscode.postMessage({ command: 'apply', finding: ${JSON.stringify(finding)} });
        }
        function cancel() {
          vscode.postMessage({ command: 'cancel' });
        }
      </script>
    </body>
    </html>
  `;

  // 监听 webview 消息
  panel.webview.onDidReceiveMessage(async (msg) => {
    if (msg.command === 'apply') {
      await applyFixCommand(finding, panel);
    } else if (msg.command === 'cancel') {
      panel.dispose();
    }
  });
}

function escapeHtml(s: string): string {
  return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/**
 * Apply Fix 核心实现：用 finding.suggestion 作为 new code，
 * 通过 vscode.WorkspaceEdit 替换文件对应行。
 *
 * v1.2 简化策略：替换 finding.line 行为 newCode（覆盖该行）。
 * v1.3 可改成"多行替换"或"调用后端 /api/fixes 拿 diff"。
 */
export async function applyFixCommand(
  finding: Finding,
  panel?: vscode.WebviewPanel
): Promise<void> {
  if (!finding.suggestion) {
    vscode.window.showErrorMessage('该 finding 没有修复建议（suggestion 为空）');
    return;
  }

  // 找匹配的文件
  const files = await vscode.workspace.findFiles(`**/${finding.file}`, '**/node_modules/**');
  if (files.length === 0) {
    vscode.window.showErrorMessage(`未找到文件：${finding.file}`);
    return;
  }

  const uri = files[0];
  const doc = await vscode.workspace.openTextDocument(uri);
  await vscode.window.showTextDocument(doc);

  const line = Math.max(0, finding.line - 1);
  if (line >= doc.lineCount) {
    vscode.window.showErrorMessage(`行号 ${finding.line} 超出文件范围`);
    return;
  }

  // 替换该行
  const edit = new vscode.WorkspaceEdit();
  const range = new vscode.Range(line, 0, line, doc.lineAt(line).text.length);
  edit.replace(uri, range, finding.suggestion);

  const applied = await vscode.workspace.applyEdit(edit);
  if (applied) {
    vscode.window.showInformationMessage(
      `✅ 已应用修复：${finding.file}:${finding.line}`
    );
    panel?.dispose();
  } else {
    vscode.window.showErrorMessage('应用修复失败');
  }
}