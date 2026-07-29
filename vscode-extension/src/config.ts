/**
 * 扩展配置 + SecretStorage 封装
 *
 * - API base URL、GitHub token 等配置
 * - Token 存在 SecretStorage 里（加密），不会明文存到 settings.json
 */
import * as vscode from 'vscode';

const TOKEN_KEY = 'ai-pr-review.github-token';

export function getApiBaseUrl(): string {
  const config = vscode.workspace.getConfiguration('ai-pr-review');
  return config.get<string>('apiBaseUrl', 'http://127.0.0.1:8765');
}

export function getGithubToken(): string {
  // 优先从 SecretStorage 读
  // 注：SecretStorage 是异步的，VS Code 提供 get() 同步 API
  // 我们用 ExtensionContext.context 注入的 SecretStorage
  const session = (global as any).__aiPrReviewSession;
  if (session) return session;

  // 降级：从 settings.json 读（明文，不推荐）
  const config = vscode.workspace.getConfiguration('ai-pr-review');
  return config.get<string>('githubToken', '');
}

export function setGithubToken(context: vscode.ExtensionContext, token: string): Thenable<void> {
  return context.secrets.store(TOKEN_KEY, token);
}

export async function clearGithubToken(context: vscode.ExtensionContext): Promise<void> {
  await context.secrets.delete(TOKEN_KEY);
}

export async function readGithubToken(context: vscode.ExtensionContext): Promise<string | undefined> {
  return await context.secrets.get(TOKEN_KEY);
}