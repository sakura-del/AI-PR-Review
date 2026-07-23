"""platform 模块测试 — 覆盖 URL 识别、工厂函数、GitLab API 调用 mock"""
import json
import pytest
from unittest.mock import patch, MagicMock
from ai_pr_review.platform import (
    GitPlatform,
    GitHubPlatform,
    GitLabPlatform,
    parse_gitlab_url,
    is_gitlab_url,
    is_github_url,
    create_platform,
)
from ai_pr_review.models import PRMetadata


# ===== URL 识别函数测试 =====

def test_is_gitlab_url_positive():
    assert is_gitlab_url("https://gitlab.com/o/r/-/merge_requests/1") is True


def test_is_gitlab_url_self_hosted():
    assert is_gitlab_url("https://git.company.com/team/proj/-/merge_requests/42") is True


def test_is_gitlab_url_negative_github():
    assert is_gitlab_url("https://github.com/o/r/pull/1") is False


def test_is_github_url_positive():
    assert is_github_url("https://github.com/o/r/pull/1") is True


def test_is_github_url_negative_gitlab():
    assert is_github_url("https://gitlab.com/o/r/-/merge_requests/1") is False


def test_is_github_url_negative_other():
    assert is_github_url("https://example.com/foo") is False


# ===== parse_gitlab_url 测试 =====

def test_parse_gitlab_url_basic():
    host, owner, repo, number = parse_gitlab_url(
        "https://gitlab.com/team/project/-/merge_requests/42"
    )
    assert host == "gitlab.com"
    assert owner == "team"
    assert repo == "project"
    assert number == 42


def test_parse_gitlab_url_self_hosted():
    host, owner, repo, number = parse_gitlab_url(
        "https://git.internal.com/group/sub-group/repo/-/merge_requests/7"
    )
    assert host == "git.internal.com"
    assert number == 7


def test_parse_gitlab_url_invalid():
    with pytest.raises(ValueError):
        parse_gitlab_url("https://github.com/o/r/pull/1")


# ===== create_platform 工厂测试 =====

def test_create_platform_github():
    platform = create_platform("https://github.com/o/r/pull/1", token="gh_token")
    assert isinstance(platform, GitHubPlatform)


def test_create_platform_gitlab():
    platform = create_platform(
        "https://gitlab.com/o/r/-/merge_requests/1", gitlab_token="gl_token"
    )
    assert isinstance(platform, GitLabPlatform)


def test_create_platform_unsupported():
    with pytest.raises(ValueError):
        create_platform("https://example.com/unknown")


def test_create_platform_gitlab_uses_gitlab_token_not_github():
    """GitLab 不应使用 GitHub token"""
    platform = create_platform(
        "https://gitlab.com/o/r/-/merge_requests/1",
        token="gh_token",
        gitlab_token="gl_token",
    )
    assert platform._token == "gl_token"


# ===== GitPlatform 抽象基类测试 =====

def test_git_platform_is_abstract():
    with pytest.raises(TypeError):
        GitPlatform()


def test_github_platform_inherits_abstract():
    platform = GitHubPlatform(token="")
    assert isinstance(platform, GitPlatform)


def test_gitlab_platform_inherits_abstract():
    platform = GitLabPlatform(token="")
    assert isinstance(platform, GitPlatform)


# ===== GitHubPlatform 委托测试 =====

def test_github_platform_delegates_to_client():
    """验证 GitHubPlatform 委托给 GitHubClient"""
    platform = GitHubPlatform(token="tok")
    assert platform._client._token == "tok"


# ===== GitLabPlatform API 调用 mock 测试 =====

def _mock_response(json_data=None, text="", status_code=200, content_type="application/json"):
    mock = MagicMock()
    mock.status_code = status_code
    mock.headers = {"content-type": content_type}
    mock.raise_for_status = MagicMock()
    if json_data is not None:
        mock.json.return_value = json_data
    mock.text = text
    return mock


def test_gitlab_get_pr_metadata():
    platform = GitLabPlatform(token="gl_token")
    mock_resp = _mock_response(json_data={
        "title": "Fix bug",
        "description": "desc",
        "author": {"username": "alice"},
        "target_branch": "main",
        "source_branch": "feature",
        "labels": ["bug"],
    })

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get = MagicMock(return_value=mock_resp)

    with patch("ai_pr_review.platform.httpx.Client", return_value=mock_client):
        meta = platform.get_pr_metadata("https://gitlab.com/o/r/-/merge_requests/1")

    assert meta.title == "Fix bug"
    assert meta.author == "alice"
    assert meta.base_branch == "main"
    assert meta.head_branch == "feature"
    assert meta.labels == ["bug"]
    assert meta.number == 1


def test_gitlab_get_pr_diff_content_text():
    platform = GitLabPlatform(token="gl_token")
    mock_resp = _mock_response(text="diff --git a/x b/x\n--- a/x\n+++ b/x\n", content_type="text/plain")

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get = MagicMock(return_value=mock_resp)

    with patch("ai_pr_review.platform.httpx.Client", return_value=mock_client):
        diff = platform.get_pr_diff_content("https://gitlab.com/o/r/-/merge_requests/1")

    assert "diff --git" in diff


def test_gitlab_get_pr_diff_content_json_fallback():
    """GitLab 返回 JSON 数组时，应转为 unified diff 文本"""
    platform = GitLabPlatform(token="gl_token")
    diffs_json = [
        {
            "old_path": "a.py",
            "new_path": "a.py",
            "new_file": False,
            "deleted_file": False,
            "diff": "@@ -1,1 +1,1 @@\n-old\n+new",
        }
    ]
    mock_resp = _mock_response(json_data=diffs_json, content_type="application/json")

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get = MagicMock(return_value=mock_resp)

    with patch("ai_pr_review.platform.httpx.Client", return_value=mock_client):
        diff = platform.get_pr_diff_content("https://gitlab.com/o/r/-/merge_requests/1")

    assert "diff --git a/a.py b/a.py" in diff
    assert "--- a/a.py" in diff
    assert "@@ -1,1 +1,1 @@" in diff


def test_gitlab_get_file_content_success():
    platform = GitLabPlatform(token="gl_token")
    mock_resp = _mock_response(text="print('hello')", content_type="text/plain")

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get = MagicMock(return_value=mock_resp)

    with patch("ai_pr_review.platform.httpx.Client", return_value=mock_client):
        content = platform.get_file_content(
            "https://gitlab.com/o/r/-/merge_requests/1", "src/app.py", "main"
        )

    assert content == "print('hello')"


def test_gitlab_get_file_content_404_returns_empty():
    platform = GitLabPlatform(token="gl_token")
    mock_resp = _mock_response(status_code=404, text="")

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get = MagicMock(return_value=mock_resp)

    with patch("ai_pr_review.platform.httpx.Client", return_value=mock_client):
        content = platform.get_file_content(
            "https://gitlab.com/o/r/-/merge_requests/1", "missing.py", "main"
        )

    assert content == ""


def test_gitlab_get_pr_head_sha():
    platform = GitLabPlatform(token="gl_token")
    versions = [{"head_commit_sha": "abc123", "id": 1}]
    mock_resp = _mock_response(json_data=versions)

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get = MagicMock(return_value=mock_resp)

    with patch("ai_pr_review.platform.httpx.Client", return_value=mock_client):
        sha = platform.get_pr_head_sha("https://gitlab.com/o/r/-/merge_requests/1")

    assert sha == "abc123"


def test_gitlab_get_pr_head_sha_empty_versions():
    platform = GitLabPlatform(token="gl_token")
    mock_resp = _mock_response(json_data=[])

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get = MagicMock(return_value=mock_resp)

    with patch("ai_pr_review.platform.httpx.Client", return_value=mock_client):
        sha = platform.get_pr_head_sha("https://gitlab.com/o/r/-/merge_requests/1")

    assert sha == ""


def test_gitlab_headers_include_token():
    platform = GitLabPlatform(token="secret123")
    headers = platform._headers()
    assert headers["PRIVATE-TOKEN"] == "secret123"


def test_gitlab_headers_without_token():
    platform = GitLabPlatform(token="")
    headers = platform._headers()
    assert "PRIVATE-TOKEN" not in headers
