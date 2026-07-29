/**
 * Auth 命令：登录、登出、显示当前用户
 */
import * as vscode from 'vscode';
import { ApiClient, ApiError } from '../api/client';
import { setGithubToken, getApiBaseUrl } from '../config';

export async function loginCommand(
  context: vscode.ExtensionContext,
  api: ApiClient,
  _getBaseUrl: () => string
): Promise<void> {
  // 两种登录方式：
  // A) 浏览器走 GitHub OAuth（需要 FastAPI /auth/login 端点）
  // B) 用户直接粘贴 PAT（更简单，适合开发）

  const choice = await vscode.window.showQuickPick(
    [
      { label: '$(browser) Browser Login (GitHub OAuth)', value: 'oauth' },
      { label: '$(key) Paste Personal Access Token', value: 'pat' },
    ],
    { placeHolder: 'How would you like to log in?' }
  );
  if (!choice) return;

  if (choice.value === 'oauth') {
    const url = `${getApiBaseUrl()}/auth/login`;
    await vscode.env.openExternal(vscode.Uri.parse(url));
    vscode.window.showInformationMessage(
      '已打开 GitHub 授权页。授权后会跳到本机 Web 完成登录。'
    );
    return;
  }

  // PAT 方式
  const token = await vscode.window.showInputBox({
    prompt: 'GitHub Personal Access Token (需 Pull requests: Read+Write 权限)',
    password: true,
    placeHolder: 'github_pat_11...',
  });
  if (!token) return;

  await setGithubToken(context, token);
  api.setToken(token);

  // 验证 token
  try {
    const me = await api.authMe();
    if (me.authenticated) {
      vscode.window.showInformationMessage(
        `✅ 已登录 @${me.github_login || me.user_id}`
      );
    } else {
      vscode.window.showWarningMessage('Token 保存成功，但 /auth/me 返回未认证。请检查 web 服务是否启动。');
    }
  } catch (e) {
    const err = e as ApiError;
    vscode.window.showErrorMessage(`Token 验证失败：${err.message}`);
  }
}

export async function logoutCommand(api: ApiClient): Promise<void> {
  // 清掉 token（SecretStorage 删除由调用方做）
  api.setToken(undefined);
  vscode.window.showInformationMessage('已登出（本地 token 已清）');
}

export async function showUserCommand(api: ApiClient): Promise<void> {
  try {
    const me = await api.authMe();
    if (me.authenticated) {
      vscode.window.showInformationMessage(
        `@${me.github_login || me.user_id}`
      );
    } else {
      vscode.window.showInformationMessage('未登录');
    }
  } catch (e) {
    const err = e as ApiError;
    vscode.window.showErrorMessage(`查询失败：${err.message}`);
  }
}