/**
 * 自动检测当前 workspace 的 PR
 *
 * 流程：
 * 1. 调 detectPrForWorkspace（多种策略）
 * 2. 找到 PR 后：拉 review 任务历史，找最近一个 succeeded 的 job
 * 3. 激活 CodeLens（setReviewContext）
 * 4. 提示用户
 */
import * as vscode from 'vscode';
import { ApiClient } from '../api/client';
import { detectPrForWorkspace } from '../pr_detector';
import { clearReviewContext } from "../providers/codelens";

export async function detectPrCommand(
  api: ApiClient,
  output: vscode.OutputChannel
): Promise<void> {
  const workspaceFolders = vscode.workspace.workspaceFolders;
  if (!workspaceFolders || workspaceFolders.length === 0) {
    vscode.window.showErrorMessage('未打开 workspace');
    return;
  }
  const root = workspaceFolders[0].uri.fsPath;

  output.appendLine(`[INFO] Detecting PR in ${root}`);

  const result = await detectPrForWorkspace(api, root);
  if (!result) {
    vscode.window.showWarningMessage(
      '未检测到当前 branch 对应的 PR。请确认已推送 branch 到 GitHub，或手动 Review PR。'
    );
    return;
  }

  output.appendLine(
    `[INFO] Detected: ${result.pr_url} (strategy=${result.strategy})`
  );

  // 拉 history 找最近 succeeded 的 job
  let jobId: string | null = null;
  try {
    const records = await api.history(50);
    const matched = records.find((r) => r.pr_url === result.pr_url);
    if (matched && (matched as any).job_id) {
      // 实际后端没在 history 返回 job_id（v0.10 没接 job_id 字段）
      // 走 list_jobs 找匹配
    }
    // 通过 list_jobs 找匹配 PR 的最近 succeeded
    const jobs = await api.listJobs(20);
    const j = jobs.find(
      (x) => x.pr_url === result.pr_url && x.status === 'succeeded'
    );
    if (j) {
      jobId = j.id;
    }
  } catch (e) {
    output.appendLine(`[WARN] failed to find job: ${(e as Error).message}`);
  }

  if (!jobId) {
    const choice = await vscode.window.showInformationMessage(
      `检测到 PR #${result.number}，但未找到已完成的 review 任务。\n是否现在提交审查？`,
      '提交 Review',
      '取消'
    );
    if (choice === '提交 Review') {
      await vscode.commands.executeCommand('ai-pr-review.reviewPR');
    }
    return;
  }

  // 拉 job 详情 + 激活 CodeLens
  try {
    const job = await api.getJob(jobId);
    if (job.status === 'succeeded') {
      await vscode.commands.executeCommand(
        'ai-pr-review.setReviewContext',
        job,
        result.pr_url
      );
    } else {
      vscode.window.showWarningMessage(
        `找到的 job 状态为 ${job.status}，未激活 CodeLens`
      );
    }
  } catch (e) {
    vscode.window.showErrorMessage(
      `加载 review 失败：${(e as Error).message}`
    );
  }
}

export async function clearContextCommand(): Promise<void> {
  clearReviewContext();
  vscode.window.showInformationMessage('已清除 CodeLens 上下文');
}