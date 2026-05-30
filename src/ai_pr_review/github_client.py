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
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        headers = {
            "Accept": "application/vnd.github.v3.diff",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        diff_url = f"https://github.com/{owner}/{repo_name}/pull/{number}.diff"

        session = requests.Session()
        retry = Retry(total=3, backoff_factor=2, status_forcelist=[500, 502, 503, 504])
        session.mount("https://", HTTPAdapter(max_retries=retry))

        response = session.get(diff_url, headers=headers, timeout=120)
        if response.status_code == 406 or response.status_code == 302:
            headers = {
                "Accept": "text/plain",
            }
            if self._token:
                headers["Authorization"] = f"Bearer {self._token}"
            response = session.get(diff_url, headers=headers, timeout=120)
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

    def create_review_with_comments(self, url: str, body: str, comments: list[dict], event: str = "COMMENT"):
        owner, repo_name, number = parse_pr_url(url)
        repo = self._client.get_repo(f"{owner}/{repo_name}")
        pr = repo.get_pull(number)
        pr.create_review(
            body=body,
            event=event,
            comments=comments,
        )

    def add_labels(self, url: str, labels: list[str]):
        owner, repo_name, number = parse_pr_url(url)
        repo = self._client.get_repo(f"{owner}/{repo_name}")
        pr = repo.get_pull(number)
        existing = {label.name for label in pr.labels}
        new_labels = [l for l in labels if l not in existing]
        if new_labels:
            pr.add_to_labels(*new_labels)

    def get_pr_head_sha(self, url: str) -> str:
        owner, repo_name, number = parse_pr_url(url)
        repo = self._client.get_repo(f"{owner}/{repo_name}")
        pr = repo.get_pull(number)
        return pr.head.sha

    def get_repo_pr_comments(self, url: str, max_prs: int = 20) -> list[dict]:
        owner, repo_name, _ = parse_pr_url(url)
        repo = self._client.get_repo(f"{owner}/{repo_name}")
        pulls = repo.get_pulls(state="closed", sort="updated", direction="desc")

        comments = []
        count = 0
        for pr in pulls:
            if count >= max_prs:
                break
            count += 1
            try:
                for c in pr.get_review_comments():
                    comments.append({
                        "pr_number": pr.number,
                        "pr_title": pr.title,
                        "file": c.path,
                        "line": c.line,
                        "body": c.body,
                        "author": c.user.login,
                        "created_at": str(c.created_at),
                        "comment_type": "review",
                    })
            except GithubException:
                pass

            try:
                for c in pr.get_issue_comments():
                    comments.append({
                        "pr_number": pr.number,
                        "pr_title": pr.title,
                        "file": "",
                        "line": 0,
                        "body": c.body,
                        "author": c.user.login,
                        "created_at": str(c.created_at),
                        "comment_type": "issue",
                    })
            except GithubException:
                pass

        return comments

    def get_commit_diff(self, url: str, base_sha: str, head_sha: str) -> str:
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        owner, repo_name, _ = parse_pr_url(url)
        headers = {"Accept": "application/vnd.github.v3.diff"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        compare_url = f"https://api.github.com/repos/{owner}/{repo_name}/compare/{base_sha}...{head_sha}"

        session = requests.Session()
        retry = Retry(total=3, backoff_factor=2, status_forcelist=[500, 502, 503, 504])
        session.mount("https://", HTTPAdapter(max_retries=retry))

        response = session.get(compare_url, headers=headers, timeout=120)
        response.raise_for_status()

        import json
        data = response.json()
        files = data.get("files", [])
        diff_parts = []
        for f in files:
            if f.get("patch"):
                a_path = f.get("filename", "")
                diff_parts.append(f"diff --git a/{a_path} b/{a_path}\n{f['patch']}")
        return "\n".join(diff_parts)
