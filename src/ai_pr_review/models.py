from dataclasses import dataclass, field
from enum import Enum


class ChangeType(str, Enum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


class Severity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class DiffHunk:
    file_path: str
    change_type: ChangeType
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    content: str
    header: str


@dataclass
class FileDiff:
    path: str
    change_type: ChangeType
    hunks: list[DiffHunk]
    additions: int
    deletions: int
    is_binary: bool = False
    is_generated: bool = False


@dataclass
class ParsedDiff:
    files: list[FileDiff]
    total_additions: int
    total_deletions: int


@dataclass
class PRMetadata:
    title: str
    description: str
    author: str
    base_branch: str
    head_branch: str
    labels: list[str]
    url: str
    number: int
    repo_owner: str
    repo_name: str


@dataclass
class AnalysisSummary:
    intent: str
    scope: str
    key_changes: list[str]


@dataclass
class Finding:
    type: str
    severity: Severity
    confidence: int
    expert: str
    file: str
    line: int
    title: str
    description: str
    suggestion: str
    code_snippet: str


@dataclass
class Suggestion:
    category: str
    priority: Severity
    description: str
    example: str


@dataclass
class AnalysisResult:
    summary: AnalysisSummary
    findings: list[Finding]
    suggestions: list[Suggestion]
