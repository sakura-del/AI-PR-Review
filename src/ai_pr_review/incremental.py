from ai_pr_review.models import ParsedDiff
from ai_pr_review.history import find_last_record, AnalysisRecord
from ai_pr_review.github_client import GitHubClient


class IncrementalAnalyzer:
    def __init__(self, gh_client: GitHubClient):
        self._gh_client = gh_client

    def should_analyze_incremental(self, pr_url: str) -> AnalysisRecord | None:
        last = find_last_record(pr_url)
        if not last or not last.head_sha:
            return None
        return last

    def get_incremental_diff(
        self,
        pr_url: str,
        last_sha: str,
        current_sha: str,
    ) -> str:
        if last_sha == current_sha:
            return ""
        return self._gh_client.get_commit_diff(pr_url, last_sha, current_sha)

    def build_incremental_context(
        self,
        pr_url: str,
        full_diff: ParsedDiff,
        incremental_diff: ParsedDiff,
        last_record: AnalysisRecord,
    ) -> dict:
        changed_files = [f.path for f in incremental_diff.files]
        unchanged_files = [
            f.path for f in full_diff.files if f.path not in changed_files
        ]
        return {
            "incremental_diff": incremental_diff,
            "changed_files": changed_files,
            "unchanged_files": unchanged_files,
            "last_sha": last_record.head_sha,
            "last_timestamp": last_record.timestamp,
            "is_incremental": True,
        }
