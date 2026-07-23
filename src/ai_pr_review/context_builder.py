import tiktoken
from ai_pr_review.models import ParsedDiff, FileDiff, PRMetadata
from ai_pr_review.config import AppConfig
from ai_pr_review.file_priority import sort_files_by_priority


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
        total_lines = parsed_diff.total_additions + parsed_diff.total_deletions
        if total_lines > 5000:
            self._budget = max(self._budget, 12000)
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

        # 构建跨文件依赖上下文
        if remaining_budget > 500 and self._get_file_content:
            from ai_pr_review.dependency_extractor import build_cross_file_context
            cross_file = build_cross_file_context(
                parsed_diff, self._get_file_content, "", "",
                max_files=3, max_content_length=2000
            )
            if cross_file:
                cross_tokens = _estimate_tokens(cross_file)
                if _estimate_tokens(context_parts.get("file_contents", "")) + cross_tokens < remaining_budget:
                    context_parts["cross_file_context"] = cross_file

        # 构建函数调用链上下文
        if remaining_budget > 1000 and self._get_file_content:
            from ai_pr_review.call_chain import build_call_chain_context
            call_chain = build_call_chain_context(
                parsed_diff, self._get_file_content, "", ""
            )
            if call_chain:
                call_chain_tokens = _estimate_tokens(call_chain)
                if call_chain_tokens < remaining_budget // 3:  # 限制调用链上下文不超过剩余预算的1/3
                    context_parts["call_chain_context"] = call_chain

        return context_parts

    def _build_pr_context(self, metadata: PRMetadata) -> str:
        parts = [
            f"Title: {metadata.title}",
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
            f"+{parsed_diff.total_additions} -{parsed_diff.total_deletions} / {len(parsed_diff.files)} files",
            "",
        ]

        priority_files = sort_files_by_priority(
            [f for f in parsed_diff.files if not f.is_binary and not f.is_generated]
        )

        available_budget = self._budget - 200
        used_budget = 0

        # 使用 enumerate 避免 O(n²) 的 priority_files.index(file_diff) 调用
        for idx, file_diff in enumerate(priority_files):
            if used_budget >= available_budget:
                remaining = len(priority_files) - idx
                parts.append(f"... 还有{remaining}个文件(已超出上下文限制)")
                break

            file_header = f"{file_diff.path} [{file_diff.change_type.value}]"
            file_content = self._build_file_diff(file_diff)
            file_tokens = _estimate_tokens(file_content)

            if used_budget + file_tokens > available_budget:
                parts.append(f"{file_header} (部分)")
                truncated = self._truncate_hunks(file_diff, available_budget - used_budget)
                parts.append(truncated)
                parts.append("")
                break

            parts.append(file_header)
            parts.append(file_content)
            parts.append("")
            used_budget += file_tokens

        return "\n".join(parts)

    def _build_file_diff(self, file_diff: FileDiff) -> str:
        lines = []
        for hunk in file_diff.hunks:
            lines.append(hunk.content)
        return "\n".join(lines)

    def _truncate_hunks(self, file_diff: FileDiff, budget: int) -> str:
        lines = []
        for hunk in file_diff.hunks:
            if _estimate_tokens("\n".join(lines)) + _estimate_tokens(hunk.content) > budget:
                break
            lines.append(hunk.content)
        return "\n".join(lines)

    def _build_file_contexts(
        self, parsed_diff: ParsedDiff, budget: int
    ) -> str:
        parts = []
        used = 0

        priority_files = sort_files_by_priority(
            [f for f in parsed_diff.files if not f.is_binary and not f.is_generated]
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
                parts.append(f"[truncated] {file_diff.path}\n{truncated}")
                used = budget
                break

            parts.append(f"[{file_diff.path}]\n{content}")
            used += estimated

        return "\n\n".join(parts)
