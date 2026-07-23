"""多平台适配层 — 抽象 GitPlatform 接口，支持 GitHub 与 GitLab

设计目标：
- 抽象统一接口，让上层（analyzer/cli）与具体平台解耦
- 复用现有 GitHubClient 实现，不破坏既有代码
- GitLab 客户端基于 httpx，零额外依赖（httpx 已在依赖中）
- URL 解析作为协议无关的入口，自动识别平台
"""
import re
import logging
from abc import ABC, abstractmethod
from typing import Optional

import httpx

from ai_pr_review.models import PRMetadata
from ai_pr_review.github_client import GitHubClient, parse_pr_url as parse_github_url

logger = logging.getLogger(__name__)


class GitPlatform(ABC):
    """Git 平台抽象基类 — 定义上层所需的最小接口"""

    @abstractmethod
    def get_pr_metadata(self, url: str) -> PRMetadata:
        ...

    @abstractmethod
    def get_pr_diff_content(self, url: str) -> str:
        ...

    @abstractmethod
    def get_file_content(self, url: str, file_path: str, ref: str) -> str:
        ...

    @abstractmethod
    def get_pr_head_sha(self, url: str) -> str:
        ...


class GitHubPlatform(GitPlatform):
    """GitHub 平台适配器 — 委托给现有 GitHubClient"""

    def __init__(self, token: str = ""):
        self._client = GitHubClient(token=token)

    def get_pr_metadata(self, url: str) -> PRMetadata:
        return self._client.get_pr_metadata(url)

    def get_pr_diff_content(self, url: str) -> str:
        return self._client.get_pr_diff_content(url)

    def get_file_content(self, url: str, file_path: str, ref: str) -> str:
        return self._client.get_file_content(url, file_path, ref)

    def get_pr_head_sha(self, url: str) -> str:
        return self._client.get_pr_head_sha(url)


# GitLab PR URL 模式（支持自托管实例与嵌套子组 group/sub-group/repo）
GITLAB_URL_PATTERN = re.compile(
    r"https?://(?P<host>[^/]+)/(?P<owner>.+?)/(?P<repo>[^/]+)/-/merge_requests/(?P<number>\d+)"
)


def parse_gitlab_url(url: str) -> tuple[str, str, str, int]:
    """解析 GitLab MR URL，返回 (host, owner, repo, number)"""
    match = GITLAB_URL_PATTERN.match(url)
    if not match:
        raise ValueError(f"Invalid GitLab MR URL: {url}")
    return match.group("host"), match.group("owner"), match.group("repo"), int(match.group("number"))


def is_gitlab_url(url: str) -> bool:
    """快速判断是否为 GitLab URL（含 -/merge_requests 路径）"""
    return "/-/merge_requests/" in url


def is_github_url(url: str) -> bool:
    """快速判断是否为 GitHub URL"""
    return "github.com/" in url and "/pull/" in url


def create_platform(url: str, token: str = "", gitlab_token: str = "") -> GitPlatform:
    """工厂函数：根据 URL 自动选择平台适配器

    gitlab_token: GitLab 私人 token（与 GitHub token 独立）
    """
    if is_gitlab_url(url):
        return GitLabPlatform(token=gitlab_token)
    if is_github_url(url):
        return GitHubPlatform(token=token)
    raise ValueError(f"Unsupported platform URL: {url}")


class GitLabPlatform(GitPlatform):
    """GitLab 平台适配器 — 基于 httpx 调用 GitLab REST API

    API 文档：https://docs.gitlab.com/ee/api/merge_requests.html
    """

    def __init__(self, token: str = "", host: str = ""):
        self._token = token
        self._default_host = host

    def _api_base(self, url: str) -> tuple[str, str, str]:
        """从 MR URL 提取 (host, project_path_encoded, mr_iid)"""
        host, owner, repo, number = parse_gitlab_url(url)
        # GitLab API 要求 project path 用 URL 编码（owner/repo → owner%2Frepo）
        project_encoded = f"{owner}%2F{repo}"
        return host, project_encoded, str(number)

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._token:
            headers["PRIVATE-TOKEN"] = self._token
        return headers

    def _api_url(self, host: str, path: str) -> str:
        """构造完整 API URL"""
        return f"https://{host}/api/v4{path}"

    def get_pr_metadata(self, url: str) -> PRMetadata:
        host, project, mr_iid = self._api_base(url)
        api_url = self._api_url(host, f"/projects/{project}/merge_requests/{mr_iid}")

        transport = httpx.HTTPTransport(retries=3)
        with httpx.Client(transport=transport, timeout=60.0) as client:
            resp = client.get(api_url, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()

        return PRMetadata(
            title=data.get("title", ""),
            description=data.get("description", "") or "",
            author=data.get("author", {}).get("username", ""),
            base_branch=data.get("target_branch", ""),
            head_branch=data.get("source_branch", ""),
            labels=data.get("labels", []),
            url=url,
            number=int(mr_iid),
            repo_owner=data.get("target_project_id", ""),
            repo_name=project,
        )

    def get_pr_diff_content(self, url: str) -> str:
        host, project, mr_iid = self._api_base(url)
        # GitLab 提供 .diff 扩展直接获取 diff 文本
        api_url = self._api_url(host, f"/projects/{project}/merge_requests/{mr_iid}/diffs")

        transport = httpx.HTTPTransport(retries=3)
        headers = self._headers()
        headers["Accept"] = "text/plain"
        with httpx.Client(transport=transport, timeout=120.0) as client:
            resp = client.get(api_url, headers=headers)
            # 退化策略：若返回 JSON 数组，拼接为 diff 文本
            if resp.headers.get("content-type", "").startswith("application/json"):
                return self._diffs_to_text(resp.json())
            resp.raise_for_status()
            return resp.text

    def _diffs_to_text(self, diffs: list[dict]) -> str:
        """将 GitLab diffs JSON 数组转为标准 unified diff 文本"""
        parts = []
        for d in diffs:
            old_path = d.get("old_path", "")
            new_path = d.get("new_path", "")
            parts.append(f"diff --git a/{old_path} b/{new_path}")
            if d.get("new_file"):
                parts.append(f"new file mode 100644")
            elif d.get("deleted_file"):
                parts.append(f"deleted file mode 100644")
            parts.append(f"--- a/{old_path}")
            parts.append(f"+++ b/{new_path}")
            parts.append(d.get("diff", ""))
        return "\n".join(parts)

    def get_file_content(self, url: str, file_path: str, ref: str) -> str:
        host, project, _ = self._api_base(url)
        encoded_path = file_path.replace("/", "%2F")
        api_url = self._api_url(
            host, f"/projects/{project}/repository/files/{encoded_path}/raw"
        )
        transport = httpx.HTTPTransport(retries=3)
        with httpx.Client(transport=transport, timeout=60.0) as client:
            resp = client.get(api_url, headers=self._headers(), params={"ref": ref})
            if resp.status_code == 404:
                return ""
            resp.raise_for_status()
            return resp.text

    def get_pr_head_sha(self, url: str) -> str:
        host, project, mr_iid = self._api_base(url)
        api_url = self._api_url(host, f"/projects/{project}/merge_requests/{mr_iid}/versions")
        transport = httpx.HTTPTransport(retries=3)
        with httpx.Client(transport=transport, timeout=60.0) as client:
            resp = client.get(api_url, headers=self._headers())
            resp.raise_for_status()
            versions = resp.json()
        if not versions:
            return ""
        # 取最新版本的 head_commit_sha
        return versions[0].get("head_commit_sha", "")
