/**
 * pr_detector 单元测试
 */
import { parseBranchToPrNumber, parseGitHubRemote } from '../pr_detector';

describe('parseBranchToPrNumber', () => {
  test.each([
    ['pr/123', 123],
    ['PR-123', 123],
    ['pr-456', 456],
    ['123-fix-bug', 123],
    ['123-add-feature', 123],
    ['feat/pr-789', 789],
    ['feat/42-new-thing', 42],
    ['main', null],
    ['feat/some-feature', null],
    ['', null],
  ])('branch %s → %s', (branch, expected) => {
    expect(parseBranchToPrNumber(branch)).toBe(expected);
  });
});

describe('parseGitHubRemote', () => {
  test.each([
    [
      'https://github.com/owner/repo.git',
      { owner: 'owner', repo: 'repo' },
    ],
    [
      'https://github.com/owner/repo',
      { owner: 'owner', repo: 'repo' },
    ],
    [
      'git@github.com:owner/repo.git',
      { owner: 'owner', repo: 'repo' },
    ],
    [
      'git@github.com:owner/repo',
      { owner: 'owner', repo: 'repo' },
    ],
    [
      'https://gitlab.com/owner/repo.git',
      null, // 不支持 GitLab
    ],
    [
      'not-a-url',
      null,
    ],
  ])('URL %s → %o', (url, expected) => {
    expect(parseGitHubRemote(url)).toEqual(expected);
  });
});