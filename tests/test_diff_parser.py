from pathlib import Path
from ai_pr_review.diff_parser import parse_diff
from ai_pr_review.models import ChangeType


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_parse_diff_returns_parsed_diff():
    diff_text = (FIXTURES_DIR / "sample.diff").read_text()
    result = parse_diff(diff_text)
    assert result is not None
    assert len(result.files) == 3


def test_parse_diff_detects_added_file():
    diff_text = (FIXTURES_DIR / "sample.diff").read_text()
    result = parse_diff(diff_text)
    auth_file = next(f for f in result.files if f.path == "src/auth.py")
    assert auth_file.change_type == ChangeType.ADDED
    assert auth_file.additions > 0
    assert auth_file.deletions == 0


def test_parse_diff_detects_modified_file():
    diff_text = (FIXTURES_DIR / "sample.diff").read_text()
    result = parse_diff(diff_text)
    db_file = next(f for f in result.files if f.path == "src/db.py")
    assert db_file.change_type == ChangeType.MODIFIED
    assert db_file.additions > 0
    assert db_file.deletions > 0


def test_parse_diff_detects_deleted_file():
    diff_text = (FIXTURES_DIR / "sample.diff").read_text()
    result = parse_diff(diff_text)
    lock_file = next(f for f in result.files if f.path == "package-lock.json")
    assert lock_file.change_type == ChangeType.DELETED


def test_parse_diff_counts_totals():
    diff_text = (FIXTURES_DIR / "sample.diff").read_text()
    result = parse_diff(diff_text)
    assert result.total_additions > 0
    assert result.total_deletions > 0


def test_parse_diff_extracts_hunks():
    diff_text = (FIXTURES_DIR / "sample.diff").read_text()
    result = parse_diff(diff_text)
    db_file = next(f for f in result.files if f.path == "src/db.py")
    assert len(db_file.hunks) >= 1
    hunk = db_file.hunks[0]
    assert hunk.old_start >= 0
    assert hunk.new_start >= 0
    assert len(hunk.content) > 0


def test_parse_diff_marks_generated_files():
    diff_text = (FIXTURES_DIR / "sample.diff").read_text()
    result = parse_diff(diff_text)
    lock_file = next(f for f in result.files if f.path == "package-lock.json")
    assert lock_file.is_generated is True


def test_parse_empty_diff():
    result = parse_diff("")
    assert len(result.files) == 0
    assert result.total_additions == 0
    assert result.total_deletions == 0
