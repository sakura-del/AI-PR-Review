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

export class AiPrReviewCodeLensProvider implements vscode.CodeLensProvider {
  constructor(_api: ApiClient) {}

  async provideCodeLenses(document: vscode.TextDocument): Promise<vscode.CodeLens[]> {
    if (!currentContext) return [];

    const filePath = this.normalizePath(document.uri.fsPath);
    const findings = currentContext.files_with_findings.get(filePath) || [];
    if (findings.length === 0) return [];

    const lenses: vscode.CodeLens[] = [];
    for (const f of findings) {
      const line = Math.max(0, f.line - 1); // 1-based → 0-based
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

  /**
   * 把绝对路径规范化为相对于仓库根的相对路径（与后端 finding.file 一致）
   * 简单实现：取 basename 匹配（生产环境应读 .git 根）
   */
  private normalizePath(p: string): string {
    return p.split(/[\\/]/).pop() || p;
  }
}

export async function showFindingDetailCommand(finding: Finding): Promise<void> {
  const panel = vscode.window.createWebviewPanel(
    'ai-pr-review.finding',
    `Finding: ${finding.title}`,
    vscode.ViewColumn.Beside,
    { enableScripts: true }
  );
  panel.webview.html = `
    <html><body style="font-family: sans-serif; padding: 20px; line-height: 1.5">
      <h1>🤖 ${finding.severity} · ${finding.title}</h1>
      <p><code>${finding.file}:${finding.line}</code></p>
      <h2>描述</h2>
      <p>${finding.description}</p>
      <h2>建议</h2>
      <p>${finding.suggestion}</p>
      ${finding.code_snippet ? `<h2>代码片段</h2><pre><code>${finding.code_snippet}</code></pre>` : ''}
    </body></html>
  `;
}