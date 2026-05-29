import logging
from ai_pr_review.github_client import GitHubClient
from ai_pr_review.models import AnalysisResult
from ai_pr_review.formatter import format_github_comment

logger = logging.getLogger(__name__)


class Commenter:
    def __init__(self, client: GitHubClient):
        self._client = client

    def post_review(self, url: str, result: AnalysisResult, event: str = "COMMENT"):
        body = format_github_comment(result)
        try:
            self._client.create_review(url, body=body, event=event)
            logger.info(f"Successfully posted review to {url}")
        except Exception as e:
            logger.error(f"Failed to post review: {e}")
            raise

    def post_summary_comment(self, url: str, result: AnalysisResult):
        body = format_github_comment(result)
        try:
            self._client.create_pr_comment(url, body=body)
            logger.info(f"Successfully posted summary comment to {url}")
        except Exception as e:
            logger.error(f"Failed to post summary comment: {e}")
            raise

    def post_inline_comments(self, url: str, result: AnalysisResult, commit_id: str):
        for finding in result.findings:
            if finding.line > 0 and finding.file:
                body = (
                    f"**[{finding.severity.value.upper()}] {finding.title}** _({finding.expert})_\n\n"
                    f"{finding.description}\n\n"
                    f"💡 **建议**：{finding.suggestion}"
                )
                if finding.code_snippet:
                    body += f"\n\n相关代码：`{finding.code_snippet}`"
                try:
                    self._client.create_review_comment(
                        url,
                        commit_id=commit_id,
                        path=finding.file,
                        line=finding.line,
                        body=body,
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to post inline comment for {finding.file}:L{finding.line}: {e}"
                    )

    def post_review_with_inline_comments(self, url: str, result: AnalysisResult, commit_id: str = "", event: str = "COMMENT"):
        body = format_github_comment(result)
        inline_comments = []

        for finding in result.findings:
            if finding.line > 0 and finding.file:
                comment_body = (
                    f"**[{finding.severity.value.upper()}] {finding.title}** _({finding.expert})_\n\n"
                    f"{finding.description}\n\n"
                    f"💡 **建议**：{finding.suggestion}"
                )
                if finding.code_snippet:
                    comment_body += f"\n\n相关代码：`{finding.code_snippet}`"
                inline_comments.append({
                    "path": finding.file,
                    "line": finding.line,
                    "body": comment_body,
                })

        try:
            if inline_comments:
                self._client.create_review_with_comments(url, body=body, comments=inline_comments, event=event)
            else:
                self._client.create_review(url, body=body, event=event)
            logger.info(f"Successfully posted review with {len(inline_comments)} inline comments to {url}")
        except Exception as e:
            logger.error(f"Failed to post review with inline comments: {e}")
            raise
