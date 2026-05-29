from ai_pr_review.models import DiffHunk, FileDiff, ParsedDiff, PRMetadata, Finding, AnalysisResult, Severity, ChangeType, AnalysisSummary, Suggestion


def test_diff_hunk_creation():
    hunk = DiffHunk(
        file_path="src/main.py",
        change_type=ChangeType.MODIFIED,
        old_start=10,
        old_count=5,
        new_start=10,
        new_count=8,
        content="@@ -10,5 +10,8 @@\n-old line\n+new line\n+added line",
        header="@@ -10,5 +10,8 @@ def process():",
    )
    assert hunk.file_path == "src/main.py"
    assert hunk.change_type == ChangeType.MODIFIED
    assert hunk.old_start == 10
    assert hunk.new_count == 8


def test_file_diff_creation():
    hunk = DiffHunk(
        file_path="app.py",
        change_type=ChangeType.ADDED,
        old_start=0,
        old_count=0,
        new_start=1,
        new_count=10,
        content="new file content",
        header="@@ -0,0 +1,10 @@",
    )
    file_diff = FileDiff(
        path="app.py",
        change_type=ChangeType.ADDED,
        hunks=[hunk],
        additions=10,
        deletions=0,
        is_binary=False,
        is_generated=False,
    )
    assert file_diff.path == "app.py"
    assert len(file_diff.hunks) == 1
    assert file_diff.is_binary is False


def test_parsed_diff_stats():
    file1 = FileDiff(
        path="a.py",
        change_type=ChangeType.MODIFIED,
        hunks=[],
        additions=5,
        deletions=3,
        is_binary=False,
        is_generated=False,
    )
    file2 = FileDiff(
        path="b.py",
        change_type=ChangeType.ADDED,
        hunks=[],
        additions=20,
        deletions=0,
        is_binary=False,
        is_generated=False,
    )
    parsed = ParsedDiff(files=[file1, file2], total_additions=25, total_deletions=3)
    assert parsed.total_additions == 25
    assert parsed.total_deletions == 3
    assert len(parsed.files) == 2


def test_pr_metadata_creation():
    meta = PRMetadata(
        title="Add auth module",
        description="Implements JWT authentication",
        author="developer",
        base_branch="main",
        head_branch="feature/auth",
        labels=["enhancement"],
        url="https://github.com/owner/repo/pull/1",
        number=1,
        repo_owner="owner",
        repo_name="repo",
    )
    assert meta.title == "Add auth module"
    assert meta.number == 1


def test_finding_creation():
    finding = Finding(
        type="risk",
        severity=Severity.HIGH,
        confidence=4,
        expert="security",
        file="db.py",
        line=45,
        title="SQL Injection",
        description="User input directly concatenated into SQL query",
        suggestion="Use parameterized queries",
        code_snippet='query = f"SELECT * FROM users WHERE id = {user_id}"',
    )
    assert finding.severity == Severity.HIGH
    assert finding.confidence == 4
    assert finding.expert == "security"


def test_analysis_result_creation():
    result = AnalysisResult(
        summary=AnalysisSummary(
            intent="Add JWT authentication",
            scope="Authentication module",
            key_changes=["New auth.py module", "Updated middleware"],
        ),
        findings=[
            Finding(
                type="risk",
                severity=Severity.HIGH,
                confidence=4,
                expert="security",
                file="auth.py",
                line=10,
                title="Hardcoded secret",
                description="JWT secret is hardcoded",
                suggestion="Use environment variable",
                code_snippet="secret = 'my-secret'",
            )
        ],
        suggestions=[
            Suggestion(
                category="security",
                priority=Severity.HIGH,
                description="Move secrets to environment variables",
                example="secret = os.environ['JWT_SECRET']",
            )
        ],
    )
    assert len(result.findings) == 1
    assert result.summary.intent == "Add JWT authentication"
