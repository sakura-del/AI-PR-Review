import re
from ai_pr_review.models import DiffHunk, FileDiff, ParsedDiff, ChangeType

GENERATED_PATTERNS = re.compile(
    r"(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|\.generated\.|go\.sum|poetry\.lock|Gemfile\.lock|cargo\.lock)",
    re.IGNORECASE,
)

FILE_HEADER_PATTERN = re.compile(r"^diff --git a/(.*?) b/(.*?)$", re.MULTILINE)
NEW_FILE_PATTERN = re.compile(r"^new file mode", re.MULTILINE)
DELETED_FILE_PATTERN = re.compile(r"^deleted file mode", re.MULTILINE)
HUNK_HEADER_PATTERN = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$", re.MULTILINE
)
BINARY_PATTERN = re.compile(r"^Binary files", re.MULTILINE)
RENAMED_PATTERN = re.compile(r"^rename from ", re.MULTILINE)


def _determine_change_type(diff_section: str) -> ChangeType:
    if NEW_FILE_PATTERN.search(diff_section):
        return ChangeType.ADDED
    if DELETED_FILE_PATTERN.search(diff_section):
        return ChangeType.DELETED
    if RENAMED_PATTERN.search(diff_section):
        return ChangeType.RENAMED
    return ChangeType.MODIFIED


def _is_binary(diff_section: str) -> bool:
    return bool(BINARY_PATTERN.search(diff_section))


def _is_generated(path: str) -> bool:
    return bool(GENERATED_PATTERNS.search(path))


def _parse_hunks(diff_section: str, file_path: str, change_type: ChangeType) -> list[DiffHunk]:
    hunks = []
    hunk_matches = list(HUNK_HEADER_PATTERN.finditer(diff_section))

    for i, match in enumerate(hunk_matches):
        old_start = int(match.group(1))
        old_count = int(match.group(2)) if match.group(2) else 1
        new_start = int(match.group(3))
        new_count = int(match.group(4)) if match.group(4) else 1
        header = match.group(0)

        end_pos = (
            hunk_matches[i + 1].start() if i + 1 < len(hunk_matches) else len(diff_section)
        )
        content = diff_section[match.start() : end_pos]

        hunks.append(
            DiffHunk(
                file_path=file_path,
                change_type=change_type,
                old_start=old_start,
                old_count=old_count,
                new_start=new_start,
                new_count=new_count,
                content=content,
                header=header,
            )
        )

    return hunks


def _count_additions_deletions(hunks: list[DiffHunk]) -> tuple[int, int]:
    additions = 0
    deletions = 0
    for hunk in hunks:
        for line in hunk.content.split("\n"):
            if line.startswith("+") and not line.startswith("+++"):
                additions += 1
            elif line.startswith("-") and not line.startswith("---"):
                deletions += 1
    return additions, deletions


def parse_diff(diff_text: str) -> ParsedDiff:
    if not diff_text.strip():
        return ParsedDiff(files=[], total_additions=0, total_deletions=0)

    file_sections = FILE_HEADER_PATTERN.split(diff_text)
    files = []
    total_additions = 0
    total_deletions = 0

    for i in range(1, len(file_sections), 3):
        a_path = file_sections[i]
        b_path = file_sections[i + 1]
        section_content = file_sections[i + 2] if i + 2 < len(file_sections) else ""

        file_path = b_path if b_path else a_path
        diff_section = f"diff --git a/{a_path} b/{b_path}{section_content}"

        change_type = _determine_change_type(diff_section)
        is_binary = _is_binary(diff_section)
        is_generated = _is_generated(file_path)

        hunks = _parse_hunks(diff_section, file_path, change_type) if not is_binary else []
        additions, deletions = _count_additions_deletions(hunks)

        files.append(
            FileDiff(
                path=file_path,
                change_type=change_type,
                hunks=hunks,
                additions=additions,
                deletions=deletions,
                is_binary=is_binary,
                is_generated=is_generated,
            )
        )
        total_additions += additions
        total_deletions += deletions

    return ParsedDiff(
        files=files,
        total_additions=total_additions,
        total_deletions=total_deletions,
    )
