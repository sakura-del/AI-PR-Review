/**
 * AI PR Review VS Code 扩展入口
 *
 * v1.0 MVP: 调 FastAPI Web 后端的 HTTP 客户端 + 命令注册
 *
 * 流程：
 * 1. 用户在命令面板执行 "AI PR Review: Review PR"
 * 2. 弹输入框收 PR URL
 * 3. POST /api/jobs/ 提交审查
 * 4. 轮询 GET /api/jobs/{id} 等到 succeeded
 * 5. 在 Markdown Webview 展示 finding / suggestion
 */
import * as vscode from 'vscode';
import { ApiClient } from './api/client';
import { loginCommand, logoutCommand, showUserCommand } from './commands/auth';
import { reviewPRCommand, showJobCommand } from './commands/review';
import { showDashboardCommand } from './commands/dashboard';
import { getApiBaseUrl, getGithubToken } from './config';

let outputChannel: vscode.OutputChannel;

export function activate(context: vscode.ExtensionContext) {
  outputChannel = vscode.window.createOutputChannel('AI PR Review');
  outputChannel.appendLine('AI PR Review extension activated');

  // 初始化 HTTP 客户端
  const api = new ApiClient({
    baseUrl: getApiBaseUrl(),
    token: getGithubToken() || undefined,
  });

  // 注册命令
  context.subscriptions.push(
    vscode.commands.registerCommand('ai-pr-review.login', () =>
      loginCommand(context, api, () => getApiBaseUrl())
    ),
    vscode.commands.registerCommand('ai-pr-review.logout', () =>
      logoutCommand(api)
    ),
    vscode.commands.registerCommand('ai-pr-review.showUser', () =>
      showUserCommand(api)
    ),
    vscode.commands.registerCommand('ai-pr-review.reviewPR', () =>
      reviewPRCommand(api, outputChannel)
    ),
    vscode.commands.registerCommand('ai-pr-review.showJob', () =>
      showJobCommand(api, outputChannel)
    ),
    vscode.commands.registerCommand('ai-pr-review.showDashboard', () =>
      showDashboardCommand(context, api, outputChannel)
    ),

    // 监听配置变更
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration('ai-pr-review.apiBaseUrl')) {
        api.setBaseUrl(getApiBaseUrl());
        outputChannel.appendLine(`API base URL changed → ${getApiBaseUrl()}`);
      }
    }),

    outputChannel
  );
}

export function deactivate() {
  outputChannel?.appendLine('AI PR Review extension deactivated');
  outputChannel?.dispose();
}