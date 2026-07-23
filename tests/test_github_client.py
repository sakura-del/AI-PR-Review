"""GitHubClient 单元测试。

所有 GitHub API 调用均通过 mock 隔离，避免真实网络请求。
"""
import pytest
from unittest.mock import patch, MagicMock

from github import GithubException

from ai_pr_review.github_client import GitHubClient, parse_pr_url
from ai_pr_review.models import PRMetadata


# 统一的测试用 PR URL
PR_URL = "https://github.com/octocat/Hello-World/pull/42"


@pytest.fixture
def mock_github():
    """mock github.Github 构造函数，返回 mock 客户端实例。"""
    with patch("ai_pr_review.github_client.Github") as mock_github_class:
        mock_client = MagicMock()
        mock_github_class.return_value = mock_client
        yield mock_client


@pytest.fixture
def client(mock_github):
    """带 token 的 GitHubClient，token 用于验证 Authorization 请求头。"""
    return GitHubClient(token="fake-token")


def _make_mock_pr(
    title="Test PR",
    body="Test body",
    author="octocat",
    base_ref="main",
    head_ref="feature",
    labels=None,
    head_sha="abc123",
    number=42,
):
    """构造 mock PR 对象，统一字段访问方式。"""
    pr = MagicMock()
    pr.title = title
    pr.body = body
    pr.user.login = author
    pr.base.ref = base_ref
    pr.head.ref = head_ref
    pr.head.sha = head_sha
    pr.number = number
    # labels 为带 name 属性的对象列表
    label_objs = []
    for name in (labels or []):
        lbl = MagicMock()
        lbl.name = name
        label_objs.append(lbl)
    pr.labels = label_objs
    return pr


class TestParsePrUrl:
    def test_parse_normal_url(self):
        # 正常 URL 解析为 (owner, repo, number) 三元组
        owner, repo, number = parse_pr_url(PR_URL)
        assert owner == "octocat"
        assert repo == "Hello-World"
        assert number == 42
        assert isinstance(number, int)

    def test_parse_invalid_url_raises_value_error(self):
        # 非 PR URL（如 issues 链接）应抛出 ValueError
        with pytest.raises(ValueError):
            parse_pr_url("https://github.com/octocat/Hello-World/issues/42")


class TestGetPrMetadata:
    def test_returns_correct_pr_metadata_fields(self, client, mock_github):
        # get_pr_metadata 应将 PR 字段正确组装为 PRMetadata
        mock_repo = MagicMock()
        mock_github.get_repo.return_value = mock_repo
        mock_repo.get_pull.return_value = _make_mock_pr(
            title="Add feature",
            body="Description here",
            author="alice",
            base_ref="main",
            head_ref="dev",
            labels=["bug", "ui"],
        )

        meta = client.get_pr_metadata(PR_URL)

        assert isinstance(meta, PRMetadata)
        assert meta.title == "Add feature"
        assert meta.description == "Description here"
        assert meta.author == "alice"
        assert meta.base_branch == "main"
        assert meta.head_branch == "dev"
        assert meta.labels == ["bug", "ui"]
        assert meta.url == PR_URL
        assert meta.number == 42
        assert meta.repo_owner == "octocat"
        assert meta.repo_name == "Hello-World"
        mock_github.get_repo.assert_called_once_with("octocat/Hello-World")
        mock_repo.get_pull.assert_called_once_with(42)

    def test_none_body_becomes_empty_string(self, client, mock_github):
        # PR body 为 None 时 description 应为空字符串
        mock_repo = MagicMock()
        mock_github.get_repo.return_value = mock_repo
        mock_repo.get_pull.return_value = _make_mock_pr(body=None)

        meta = client.get_pr_metadata(PR_URL)
        assert meta.description == ""


class TestGetPrDiffContent:
    def test_delegates_to_fetch_diff_via_api(self, client, mock_github):
        # get_pr_diff_content 应委托给 _fetch_diff_via_api 并返回其结果
        mock_repo = MagicMock()
        mock_github.get_repo.return_value = mock_repo
        mock_repo.get_pull.return_value = _make_mock_pr()

        with patch.object(
            client, "_fetch_diff_via_api", return_value="diff text"
        ) as mock_fetch:
            result = client.get_pr_diff_content(PR_URL)

        assert result == "diff text"
        mock_fetch.assert_called_once_with("octocat", "Hello-World", 42)


class TestFetchDiffViaApi:
    def test_builds_url_and_headers_with_token(self, client):
        # 带 token 时请求头应包含 Authorization，URL 应指向 .diff 端点
        with patch("ai_pr_review.github_client.httpx.Client") as mock_client_cls:
            mock_http = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = "diff content"
            mock_response.raise_for_status = MagicMock()
            mock_http.get.return_value = mock_response
            mock_client_cls.return_value.__enter__.return_value = mock_http

            result = client._fetch_diff_via_api("octocat", "Hello-World", 42)

        assert result == "diff content"
        # 验证 URL 构造
        expected_url = "https://github.com/octocat/Hello-World/pull/42.diff"
        mock_http.get.assert_called_once()
        assert mock_http.get.call_args[0][0] == expected_url
        # 验证请求头
        headers = mock_http.get.call_args[1]["headers"]
        assert headers["Accept"] == "application/vnd.github.v3.diff"
        assert headers["Authorization"] == "Bearer fake-token"

    def test_omits_authorization_without_token(self, mock_github):
        # 无 token 时请求头不应包含 Authorization
        tokenless_client = GitHubClient()
        with patch("ai_pr_review.github_client.httpx.Client") as mock_client_cls:
            mock_http = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = "diff"
            mock_response.raise_for_status = MagicMock()
            mock_http.get.return_value = mock_response
            mock_client_cls.return_value.__enter__.return_value = mock_http

            result = tokenless_client._fetch_diff_via_api("a", "b", 1)

        assert result == "diff"
        headers = mock_http.get.call_args[1]["headers"]
        assert "Authorization" not in headers


class TestGetFileContent:
    def test_returns_decoded_file_content(self, client, mock_github):
        # 正常路径返回解码后的文件内容
        mock_repo = MagicMock()
        mock_github.get_repo.return_value = mock_repo
        mock_content = MagicMock()
        mock_content.decoded_content = b"print('hello')"
        mock_repo.get_contents.return_value = mock_content

        result = client.get_file_content(PR_URL, "main.py", "main")

        assert result == "print('hello')"
        mock_repo.get_contents.assert_called_once_with("main.py", ref="main")

    def test_returns_empty_string_when_file_missing(self, client, mock_github):
        # 文件不存在（抛出 GithubException）时应返回空字符串
        mock_repo = MagicMock()
        mock_github.get_repo.return_value = mock_repo
        mock_repo.get_contents.side_effect = GithubException(404, {}, None)

        result = client.get_file_content(PR_URL, "missing.py", "main")
        assert result == ""


class TestCreateReviewComment:
    def test_calls_pr_create_review_comment_with_args(self, client, mock_github):
        # create_review_comment 应以正确参数调用 pr.create_review_comment
        mock_repo = MagicMock()
        mock_github.get_repo.return_value = mock_repo
        mock_pr = _make_mock_pr()
        mock_repo.get_pull.return_value = mock_pr
        mock_commit = MagicMock()
        mock_repo.get_commit.return_value = mock_commit

        client.create_review_comment(
            PR_URL, "abc123", "src/main.py", 10, "comment body"
        )

        mock_repo.get_commit.assert_called_once_with("abc123")
        mock_pr.create_review_comment.assert_called_once_with(
            body="comment body", commit=mock_commit, path="src/main.py", line=10
        )


class TestCreatePrComment:
    def test_calls_pr_create_issue_comment(self, client, mock_github):
        # create_pr_comment 应调用 pr.create_issue_comment
        mock_repo = MagicMock()
        mock_github.get_repo.return_value = mock_repo
        mock_pr = _make_mock_pr()
        mock_repo.get_pull.return_value = mock_pr

        client.create_pr_comment(PR_URL, "general comment")

        mock_pr.create_issue_comment.assert_called_once_with("general comment")


class TestCreateReview:
    def test_calls_pr_create_review_default_event(self, client, mock_github):
        # create_review 默认 event 为 COMMENT
        mock_repo = MagicMock()
        mock_github.get_repo.return_value = mock_repo
        mock_pr = _make_mock_pr()
        mock_repo.get_pull.return_value = mock_pr

        client.create_review(PR_URL, "review body")

        mock_pr.create_review.assert_called_once_with(
            body="review body", event="COMMENT"
        )


class TestCreateReviewWithComments:
    def test_passes_comments_to_create_review(self, client, mock_github):
        # create_review_with_comments 应传递 comments 参数
        mock_repo = MagicMock()
        mock_github.get_repo.return_value = mock_repo
        mock_pr = _make_mock_pr()
        mock_repo.get_pull.return_value = mock_pr
        comments = [
            {"path": "a.py", "line": 1, "body": "fix here"},
        ]

        client.create_review_with_comments(
            PR_URL, "body", comments, event="REQUEST_CHANGES"
        )

        mock_pr.create_review.assert_called_once_with(
            body="body", event="REQUEST_CHANGES", comments=comments
        )


class TestAddLabels:
    def test_deduplicates_existing_labels(self, client, mock_github):
        # 已存在的标签不重复添加，仅添加新标签
        mock_repo = MagicMock()
        mock_github.get_repo.return_value = mock_repo
        mock_pr = _make_mock_pr(labels=["bug", "ui"])
        mock_repo.get_pull.return_value = mock_pr

        client.add_labels(PR_URL, ["bug", "perf"])

        # 只有 perf 是新标签
        mock_pr.add_to_labels.assert_called_once_with("perf")

    def test_skips_call_when_all_labels_exist(self, client, mock_github):
        # 全部已存在时不应调用 add_to_labels
        mock_repo = MagicMock()
        mock_github.get_repo.return_value = mock_repo
        mock_pr = _make_mock_pr(labels=["bug", "ui"])
        mock_repo.get_pull.return_value = mock_pr

        client.add_labels(PR_URL, ["bug", "ui"])

        mock_pr.add_to_labels.assert_not_called()


class TestGetPrHeadSha:
    def test_returns_pr_head_sha(self, client, mock_github):
        # 应返回 pr.head.sha
        mock_repo = MagicMock()
        mock_github.get_repo.return_value = mock_repo
        mock_pr = _make_mock_pr(head_sha="deadbeef")
        mock_repo.get_pull.return_value = mock_pr

        result = client.get_pr_head_sha(PR_URL)
        assert result == "deadbeef"


class TestGetCommitDiff:
    def test_calls_compare_api_and_assembles_diff(self, client):
        # get_commit_diff 应通过 compare API 拉取并组装 patch 为 diff 文本
        with patch("ai_pr_review.github_client.httpx.Client") as mock_client_cls:
            mock_http = MagicMock()
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = {
                "files": [
                    {"filename": "a.py", "patch": "@@ -1 +1 @@"},
                    {"filename": "b.py", "patch": "@@ -2 +2 @@"},
                    {"filename": "c.py"},  # 无 patch 应被跳过
                ]
            }
            mock_http.get.return_value = mock_response
            mock_client_cls.return_value.__enter__.return_value = mock_http

            result = client.get_commit_diff(PR_URL, "base123", "head456")

        # 验证 compare URL 构造
        expected_url = (
            "https://api.github.com/repos/octocat/Hello-World/compare/base123...head456"
        )
        mock_http.get.assert_called_once()
        assert mock_http.get.call_args[0][0] == expected_url
        # 验证请求头
        headers = mock_http.get.call_args[1]["headers"]
        assert headers["Accept"] == "application/vnd.github.v3.diff"
        assert headers["Authorization"] == "Bearer fake-token"
        # 验证组装结果：包含 a.py、b.py，不包含无 patch 的 c.py
        assert "a/a.py b/a.py" in result
        assert "a/b.py b/b.py" in result
        assert "c.py" not in result
