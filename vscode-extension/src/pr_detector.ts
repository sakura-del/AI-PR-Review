/**
 * 自动检测当前 workspace/file 属于哪个 PR
 *
 * 策略（按顺序尝试）：
 * 1. 当前 branch 名匹配 `pr/<num>` 或 `PR-<num>` → 提取 num
 * 2. 当前 branch 名匹配 `<num>-<description>` → 提取 num（前提是数字在头部）
 * 3. 调 GitHub API: list PRs with head=<current-branch> → 取第一个 open PR
 *
 * 失败：返回 null，调用方提示用户手动输入
 */
import { execFile } from 'child_process';
import { promisify } from 'util';
import { ApiClient } from './api/client';

const execFileAsync = promisify(execFile);

export interface PrDetectionResult {
  pr_url: string;
  number: number;
  owner: string;
  repo: string;
  branch: string;
  strategy: 'branch-pattern' | 'github-api';
}

export async function detectCurrentBranch(workspaceRoot: string): Promise<string | null> {
  try {
    const { stdout } = await execFileAsync(
      'git',
      ['-C', workspaceRoot, 'symbolic-ref', '--short', 'HEAD'],
      { timeout: 5000 }
    );
    return stdout.trim() || null;
  } catch {
    return null;
  }
}

/**
 * 策略 1: branch 名匹配
 *  - "pr/123"  → 123
 *  - "PR-123"  → 123
 *  - "123-foo"  → 123
 *  - "feat/123-foo"  → 123
 */
export function parseBranchToPrNumber(branch: string): number | null {
  const patterns = [
    /^(?:pr|PR)[\/-](\d+)/,        // pr/123, PR-123
    /^(?:pr|PR)\/(\d+)/,           // pr/123
    /^(\d+)[\/-]/,                  // 123-foo, 123/foo
    /\/(?:pr|PR)[\/-](\d+)/,        // feat/pr-123
    /\/(\d+)[\/-]/,                 // feat/42-fix, fix/123-bug
  ];
  for (const p of patterns) {
    const m = branch.match(p);
    if (m) {
      const n = parseInt(m[1], 10);
      if (n > 0) return n;
    }
  }
  return null;
}

/**
 * 策略 2: 调 GitHub API 用当前 branch 查 open PR
 *  - GET /repos/{owner}/{repo}/pulls?head={owner}:{branch}&state=open
 *  - 返回第一个 PR
 */
export async function findPrByBranch(
  api: ApiClient,
  workspaceRoot: string,
  branch: string
): Promise<PrDetectionResult | null> {
  try {
    // 1) 取 remote URL 提取 owner/repo
    const { stdout: remoteUrl } = await execFileAsync(
      'git',
      ['-C', workspaceRoot, 'config', '--get', 'remote.origin.url'],
      { timeout: 5000 }
    );
    const parsed = parseGitHubRemote(remoteUrl.trim());
    if (!parsed) return null;

    const { owner, repo } = parsed;
    const url = `/repos/${owner}/${repo}/pulls?head=${encodeURIComponent(owner)}:${encodeURIComponent(branch)}&state=open`;
    const response = await (api as any).request('GET', url);
    const pulls = response as Array<{ number: number; html_url: string; head: { ref: string } }>;
    if (pulls.length === 0) return null;

    const pr = pulls[0];
    return {
      pr_url: pr.html_url,
      number: pr.number,
      owner,
      repo,
      branch,
      strategy: 'github-api',
    };
  } catch {
    return null;
  }
}

/**
 * 解析 GitHub remote URL：
 *   https://github.com/owner/repo.git     → { owner, repo }
 *   git@github.com:owner/repo.git         → { owner, repo }
 *   https://github.com/owner/repo          → { owner, repo }
 */
export function parseGitHubRemote(
  url: string
): { owner: string; repo: string } | null {
  // 去掉 .git 后缀
  const clean = url.replace(/\.git$/, '');

  // HTTPS: https://github.com/owner/repo[.git]
  let m = clean.match(/github\.com[/:]([^/]+)\/([^/]+)/);
  if (m) return { owner: m[1], repo: m[2] };

  // SSH: git@github.com:owner/repo[.git]
  m = clean.match(/git@github\.com:([^/]+)\/([^/]+)/);
  if (m) return { owner: m[1], repo: m[2] };

  return null;
}

/**
 * 主入口：综合多种策略检测
 */
export async function detectPrForWorkspace(
  api: ApiClient,
  workspaceRoot: string
): Promise<PrDetectionResult | null> {
  const branch = await detectCurrentBranch(workspaceRoot);
  if (!branch) return null;

  // 策略 1: branch 名匹配
  const numberFromBranch = parseBranchToPrNumber(branch);
  if (numberFromBranch) {
    const remote = await getRemoteOwnerRepo(workspaceRoot);
    if (remote) {
      return {
        pr_url: `https://github.com/${remote.owner}/${remote.repo}/pull/${numberFromBranch}`,
        number: numberFromBranch,
        owner: remote.owner,
        repo: remote.repo,
        branch,
        strategy: 'branch-pattern',
      };
    }
  }

  // 策略 2: GitHub API 查询
  return await findPrByBranch(api, workspaceRoot, branch);
}

async function getRemoteOwnerRepo(
  workspaceRoot: string
): Promise<{ owner: string; repo: string } | null> {
  try {
    const { stdout } = await execFileAsync(
      'git',
      ['-C', workspaceRoot, 'config', '--get', 'remote.origin.url'],
      { timeout: 5000 }
    );
    return parseGitHubRemote(stdout.trim());
  } catch {
    return null;
  }
}