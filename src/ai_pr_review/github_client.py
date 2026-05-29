import re
import httpx
from github import Github, GithubException
from ai_pr_review.models import PRMetadata


PR_URL_PATTERN = re.compile(
    r"https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)"
)


def parse_pr_url(url: str) -> tuple[str, str, int]:
    match = PR_URL_PATTERN.match(url)
    if not match:
        raise ValueError(f"Invalid GitHub PR URL: {url}")
    return match.group("owner"), match.group("repo"), int(match.group("number"))


class GitHubClient:
    def __init__(self, token: str = ""):
        self._token = token
        self._client = Github(token) if token else Github()

    def get_pr_metadata(self, url: str) -> PRMetadata:
        owner, repo_name, number = parse_pr_url(url)
        repo = self._client.get_repo(f"{owner}/{repo_name}")
        pr = repo.get_pull(number)

        return PRMetadata(
            title=pr.title,
            description=pr.body or "",
            author=pr.user.login,
            base_branch=pr.base.ref,
            head_branch=pr.head.ref,
            labels=[label.name for label in pr.labels],
            url=url,
            number=number,
            repo_owner=owner,
            repo_name=repo_name,
        )

    def get_pr_diff_content(self, url: str) -> str:
        owner, repo_name, number = parse_pr_url(url)
        repo = self._client.get_repo(f"{owner}/{repo_name}")
        pr = repo.get_pull(number)
        return self._fetch_diff_via_api(owner, repo_name, number)

    def _fetch_diff_via_api(self, owner: str, repo_name: str, number: int) -> str:
        import requests
        headers = {
            "Accept": "application/vnd.github.v3.diff",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        diff_url = f"https://github.com/{owner}/{repo_name}/pull/{number}.diff"
        response = requests.get(diff_url, headers=headers, timeout=60)
        if response.status_code == 406 or response.status_code == 302:
            headers = {
                "Accept": "text/plain",
            }
            if self._token:
                headers["Authorization"] = f"Bearer {self._token}"
            response = requests.get(diff_url, headers=headers, timeout=60)
        response.raise_for_status()
        return response.text

    def get_file_content(self, url: str, file_path: str, ref: str) -> str:
        owner, repo_name, _ = parse_pr_url(url)
        repo = self._client.get_repo(f"{owner}/{repo_name}")
        try:
            content = repo.get_contents(file_path, ref=ref)
            if isinstance(content, list):
                return ""
            return content.decoded_content.decode("utf-8")
        except GithubException:
            return ""

    def create_review_comment(
        self, url: str, commit_id: str, path: str, line: int, body: str
    ):
        owner, repo_name, number = parse_pr_url(url)
        repo = self._client.get_repo(f"{owner}/{repo_name}")
        pr = repo.get_pull(number)
        commit = repo.get_commit(commit_id)
        pr.create_review_comment(body=body, commit=commit, path=path, line=line)

    def create_pr_comment(self, url: str, body: str):
        owner, repo_name, number = parse_pr_url(url)
        repo = self._client.get_repo(f"{owner}/{repo_name}")
        pr = repo.get_pull(number)
        pr.create_issue_comment(body)

    def create_review(self, url: str, body: str, event: str = "COMMENT"):
        owner, repo_name, number = parse_pr_url(url)
        repo = self._client.get_repo(f"{owner}/{repo_name}")
        pr = repo.get_pull(number)
        pr.create_review(body=body, event=event)
