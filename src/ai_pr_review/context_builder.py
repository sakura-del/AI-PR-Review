import tiktoken
from ai_pr_review.models import ParsedDiff, FileDiff, PRMetadata
from ai_pr_review.config import AppConfig


def _count_tokens(text: str, model: str = "gpt-4") -> int:
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(text))


def _estimate_tokens(text: str) -> int:
    return len(text) // 4


class ContextBuilder:
    def __init__(self, config: AppConfig, get_file_content_fn=None):
        self._config = config
        self._get_file_content = get_file_content_fn
        self._budget = config.analysis.context_budget

    def build_context(
        self,
        pr_metadata: PRMetadata,
        parsed_diff: ParsedDiff,
    ) -> dict[str, str]:
        context_parts: dict[str, str] = {}

        pr_context = self._build_pr_context(pr_metadata)
        context_parts["pr_metadata"] = pr_context

        diff_context = self._build_diff_context(parsed_diff)
        context_parts["diff"] = diff_context

        remaining_budget = self._budget - _estimate_tokens(pr_context) - _estimate_tokens(diff_context)

        if remaining_budget > 500 and self._get_file_content:
            file_contexts = self._build_file_contexts(parsed_diff, remaining_budget)
            if file_contexts:
                context_parts["file_contents"] = file_contexts

        return context_parts

    def _build_pr_context(self, metadata: PRMetadata) -> str:
        parts = [
            f"PR Title: {metadata.title}",
            f"Author: {metadata.author}",
            f"Branch: {metadata.head_branch} → {metadata.base_branch}",
        ]
        if metadata.description:
            parts.append(f"Description:\n{metadata.description}")
        if metadata.labels:
            parts.append(f"Labels: {', '.join(metadata.labels)}")
        return "\n".join(parts)

    def _build_diff_context(self, parsed_diff: ParsedDiff) -> str:
        parts = [
            f"Total changes: +{parsed_diff.total_additions} -{parsed_diff.total_deletions} across {len(parsed_diff.files)} files",
            "",
        ]
        for file_diff in parsed_diff.files:
            if file_diff.is_binary:
                continue
            if file_diff.is_generated:
                parts.append(f"[SKIPPED: generated] {file_diff.path}")
                continue
            parts.append(f"--- {file_diff.path} ({file_diff.change_type.value}) ---")
            for hunk in file_diff.hunks:
                parts.append(hunk.content)
            parts.append("")
        return "\n".join(parts)

    def _build_file_contexts(
        self, parsed_diff: ParsedDiff, budget: int
    ) -> str:
        parts = []
        used = 0

        priority_files = sorted(
            [f for f in parsed_diff.files if not f.is_binary and not f.is_generated],
            key=lambda f: f.change_type.value,
        )

        for file_diff in priority_files:
            if used >= budget:
                break

            content = self._get_file_content(
                "", file_diff.path, ""
            )
            if not content:
                continue

            estimated = _estimate_tokens(content)
            if used + estimated > budget:
                truncated = content[: (budget - used) * 4]
                parts.append(f"=== {file_diff.path} (truncated) ===\n{truncated}")
                used = budget
                break

            parts.append(f"=== {file_diff.path} ===\n{content}")
            used += estimated

        return "\n\n".join(parts)
