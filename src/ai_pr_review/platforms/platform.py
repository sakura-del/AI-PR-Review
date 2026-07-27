"""多平台适配层 — 抽象 GitPlatform 接口，支持 GitHub 与 GitLab

设计目标：
- 抽象统一接口，让上层（analyzer/cli）与具体平台解耦
- 复用现有 GitHubClient 实现，不破坏既有代码
- GitLab 客户端基于 httpx，零额外依赖（httpx 已在依赖中）
- URL 解析作为协议无关的入口，自动识别平台
- v0.9：429/5xx 退避重试（GitLab 也返回 Retry-After）
"""
import asyncio
import re
import logging
from abc import ABC, abstractmethod
from typing import Optional

import httpx

from ai_pr_review.core.models import PRMetadata
from ai_pr_review.platforms.github_client import GitHubClient, parse_pr_url as parse_github_url
from ai_pr_review.core.retry import RetryConfig, retry_async

logger = logging.getLogger(__name__)


def _run_async(coro):
    """在独立 event loop 中运行协程（避开 pytest-asyncio 等已有 loop 的场景）

    asyncio.run() 在已有 loop 内会抛 RuntimeError；本方法用 new_event_loop 隔离。
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


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

    重试策略：v0.9 起 429/5xx 走指数退避 + Retry-After（与 GitHub 一致）。
    """

    # 重试配置：3 次重试，base 1s，max 30s
    _RETRY_CONFIG = RetryConfig(max_retries=3, base_delay=1.0, max_delay=30.0)

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

    async def _request_json(self, url: str, timeout: float = 60.0) -> dict:
        """异步 GET 请求，自动应用重试"""
        async with httpx.AsyncClient(timeout=timeout) as client:
            async def _do():
                resp = await client.get(url, headers=self._headers())
                resp.raise_for_status()
                return resp.json()
            return await retry_async(_do, self._RETRY_CONFIG)

    async def _request_text(self, url: str, timeout: float = 120.0) -> tuple[str, str]:
        """异步 GET 请求，返回 (text, content_type)；自动应用重试"""
        async with httpx.AsyncClient(timeout=timeout) as client:
            async def _do():
                resp = await client.get(url, headers=self._headers())
                resp.raise_for_status()
                return resp.text, resp.headers.get("content-type", "")
            return await retry_async(_do, self._RETRY_CONFIG)

    async def _request_file_content(self, url: str, ref: str, timeout: float = 60.0) -> str:
        """异步拉取原始文件内容；404 返回空串（业务约定的"文件不存在"语义）

        与 _request_text 区别：
        - 404 不抛异常（GitLab 风格的业务语义）
        - 携带 params={"ref": ref}
        """
        async with httpx.AsyncClient(timeout=timeout) as client:
            async def _fetch():
                resp = await client.get(url, headers=self._headers(), params={"ref": ref})
                if resp.status_code == 404:
                    return ""
                resp.raise_for_status()
                return resp.text
            try:
                return await retry_async(_fetch, self._RETRY_CONFIG)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    return ""
                raise

    def get_pr_metadata(self, url: str) -> PRMetadata:
        host, project, mr_iid = self._api_base(url)
        api_url = self._api_url(host, f"/projects/{project}/merge_requests/{mr_iid}")
        data = _run_async(self._request_json(api_url, timeout=60.0))

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
        api_url = self._api_url(host, f"/projects/{project}/merge_requests/{mr_iid}/diffs")
        text, content_type = _run_async(self._request_text(api_url, timeout=120.0))
        if content_type.startswith("application/json"):
            return self._diffs_to_text(_safe_parse_json(text))
        return text

    def _diffs_to_text(self, diffs: list[dict]) -> str:
        """将 GitLab diffs JSON 数组转为标准 unified diff 文本"""
        parts = []
        for d in diffs:
            old_path = d.get("old_path", "")
            new_path = d.get("new_path", "")
            parts.append(f"diff --git a/{old_path} b/{new_path}")
            if d.get("new_file"):
                parts.append("new file mode 100644")
            elif d.get("deleted_file"):
                parts.append("deleted file mode 100644")
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
        return _run_async(self._request_file_content(api_url, ref, timeout=60.0))

    def get_pr_head_sha(self, url: str) -> str:
        host, project, mr_iid = self._api_base(url)
        api_url = self._api_url(host, f"/projects/{project}/merge_requests/{mr_iid}/versions")
        versions = _run_async(self._request_json(api_url, timeout=60.0))
        if not versions:
            return ""
        return versions[0].get("head_commit_sha", "")


def _safe_parse_json(text: str) -> list:
    """容错解析 JSON 数组（GitLab diff 退化场景）"""
    import json
    try:
        result = json.loads(text)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, TypeError):
        return []