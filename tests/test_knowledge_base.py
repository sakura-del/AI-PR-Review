"""knowledge_base 模块测试 — 覆盖分词、TF-IDF、相似度检索、上下文构建"""
import json
import pytest
from pathlib import Path
from unittest.mock import patch
from ai_pr_review.knowledge_base import (
    _tokenize,
    _build_tfidf_vectors,
    _to_tfidf_vector,
    _cosine_similarity,
    _load_knowledge_base,
    _build_doc_text,
    _build_query_text,
    search_similar_reviews,
    build_similar_reviews_context,
)
from ai_pr_review.models import (
    ParsedDiff,
    FileDiff,
    DiffHunk,
    ChangeType,
    PRMetadata,
)


def _make_pr(title: str = "Fix login bug", description: str = "", files: list = None) -> PRMetadata:
    return PRMetadata(
        title=title,
        description=description,
        author="tester",
        base_branch="main",
        head_branch="feature",
        labels=[],
        url="https://github.com/owner/repo/pull/2",
        number=2,
        repo_owner="owner",
        repo_name="repo",
    )


def _make_diff(file_path: str = "src/auth.py") -> ParsedDiff:
    hunk = DiffHunk(
        file_path=file_path,
        change_type=ChangeType.MODIFIED,
        old_start=1, old_count=1,
        new_start=1, new_count=1,
        content="+def foo(): pass",
        header="@@ -1,1 +1,1 @@",
    )
    return ParsedDiff(
        files=[FileDiff(
            path=file_path, change_type=ChangeType.MODIFIED,
            hunks=[hunk], additions=1, deletions=1,
        )],
        total_additions=1,
        total_deletions=1,
    )


# ===== _tokenize 单元测试 =====

def test_tokenize_english():
    tokens = _tokenize("Fix login bug in auth module")
    assert "fix" in tokens
    assert "login" in tokens
    assert "auth" in tokens


def test_tokenize_chinese():
    tokens = _tokenize("修复登录模块的 bug")
    assert "修" in tokens
    assert "登" in tokens
    assert "bug" in tokens


def test_tokenize_empty():
    assert _tokenize("") == []
    assert _tokenize(None) == []


def test_tokenize_code_identifier():
    tokens = _tokenize("user_login_v2 endpoint")
    assert "user_login_v2" in tokens
    assert "endpoint" in tokens


# ===== TF-IDF 向量构建测试 =====

def test_build_tfidf_vectors_empty():
    vecs, idf = _build_tfidf_vectors([])
    assert vecs == []
    assert idf == {}


def test_build_tfidf_vectors_basic():
    docs = [
        ["login", "auth", "bug"],
        ["login", "session"],
        ["performance", "query"],
    ]
    vecs, idf = _build_tfidf_vectors(docs)
    assert len(vecs) == 3
    # login 出现在 2/3 文档，其 idf 应小于只出现一次的 query
    assert idf["login"] < idf["query"]
    # 向量应已归一化（L2 norm ≈ 1）
    import math
    for v in vecs:
        norm = math.sqrt(sum(x * x for x in v.values()))
        assert abs(norm - 1.0) < 1e-6


def test_to_tfidf_vector_uses_global_idf():
    docs = [["x", "y"], ["z"]]
    _, idf = _build_tfidf_vectors(docs)
    vec = _to_tfidf_vector(["x", "x", "y"], idf)
    # tf 占比：x=2/3, y=1/3
    assert vec["x"] > vec["y"]


# ===== _cosine_similarity 单元测试 =====

def test_cosine_similarity_identical():
    vec = {"a": 0.5, "b": 0.5}
    assert _cosine_similarity(vec, vec) == pytest.approx(0.5, rel=1e-3)


def test_cosine_similarity_disjoint():
    assert _cosine_similarity({"a": 1.0}, {"b": 1.0}) == 0.0


def test_cosine_similarity_empty():
    assert _cosine_similarity({}, {"a": 1.0}) == 0.0


# ===== _build_doc_text / _build_query_text 测试 =====

def test_build_doc_text_includes_findings():
    record = {
        "summary": {"intent": "修复登录", "scope": "auth", "key_changes": ["重置 token"]},
        "findings": [
            {"title": "硬编码密钥", "description": "存在风险", "file": "app.py"},
        ],
        "suggestions": [{"description": "使用环境变量"}],
    }
    text = _build_doc_text(record)
    assert "修复登录" in text
    assert "重置 token" in text
    assert "硬编码密钥" in text
    assert "存在风险" in text
    assert "使用环境变量" in text
    assert "app.py" in text


def test_build_query_text_includes_paths():
    pr = _make_pr(title="Refactor auth", description="Improve security")
    diff = _make_diff("src/auth/login.py")
    text = _build_query_text(pr, diff)
    assert "Refactor auth" in text
    assert "Improve security" in text
    # 文件路径标识符参与查询
    assert "login" in text


# ===== _load_knowledge_base 测试 =====

def test_load_knowledge_base_handles_missing_dir(tmp_path):
    with patch("ai_pr_review.knowledge_base.KB_DIR", tmp_path / "nonexistent"):
        assert _load_knowledge_base() == []


def test_load_knowledge_base_filters_invalid(tmp_path):
    # 准备 2 份有效 + 1 份损坏
    (tmp_path / "a.json").write_text(json.dumps({
        "summary": {"intent": "fix bug"},
        "findings": [{"title": "t"}],
    }), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps({
        "summary": {"intent": "refactor"},
        "suggestions": [{"description": "d"}],
    }), encoding="utf-8")
    (tmp_path / "broken.json").write_text("not json", encoding="utf-8")
    (tmp_path / "empty.json").write_text(json.dumps({}), encoding="utf-8")

    with patch("ai_pr_review.knowledge_base.KB_DIR", tmp_path):
        records = _load_knowledge_base()
    assert len(records) == 2
    intents = {r["summary"]["intent"] for r in records}
    assert intents == {"fix bug", "refactor"}


# ===== search_similar_reviews / build_similar_reviews_context 集成测试 =====

def _seed_kb(tmp_path, records: list[dict]):
    """将记录写入临时 KB_DIR"""
    for i, r in enumerate(records):
        (tmp_path / f"r{i}.json").write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")


def test_search_similar_returns_empty_when_kb_too_small(tmp_path):
    with patch("ai_pr_review.knowledge_base.KB_DIR", tmp_path):
        _seed_kb(tmp_path, [{
            "summary": {"intent": "solo"},
            "findings": [{"title": "x"}],
        }])
        pr = _make_pr()
        diff = _make_diff()
        assert search_similar_reviews(pr, diff) == []


def test_search_similar_returns_ranked_results(tmp_path):
    # 知识库：1 条高度相关（auth/login），1 条弱相关（性能），1 条无关
    records = [
        {
            "summary": {"intent": "修复登录 bug", "scope": "auth", "key_changes": ["重置 token"]},
            "findings": [{"title": "硬编码密钥", "file": "src/auth.py"}],
            "suggestions": [],
        },
        {
            "summary": {"intent": "优化数据库性能", "scope": "db", "key_changes": ["索引"]},
            "findings": [{"title": "慢查询", "file": "src/db.py"}],
            "suggestions": [],
        },
        {
            "summary": {"intent": "更新文档", "scope": "docs", "key_changes": ["README"]},
            "findings": [{"title": "拼写错误", "file": "README.md"}],
            "suggestions": [],
        },
    ]
    _seed_kb(tmp_path, records)
    with patch("ai_pr_review.knowledge_base.KB_DIR", tmp_path):
        pr = _make_pr(title="Fix login bug", description="auth module")
        diff = _make_diff("src/auth/login.py")
        results = search_similar_reviews(pr, diff, top_k=3)
    assert len(results) >= 1
    # 最相似应为 auth 那条
    top_record, top_sim = results[0]
    assert "登录" in top_record["summary"]["intent"] or "auth" in top_record["summary"]["scope"]
    assert top_sim > 0


def test_build_similar_reviews_context_returns_string(tmp_path):
    records = [
        {
            "summary": {"intent": "修复登录", "scope": "auth", "key_changes": ["token"]},
            "findings": [{"title": "硬编码", "severity": "high", "file": "auth.py"}],
            "suggestions": [],
        },
        {
            "summary": {"intent": "重构会话", "scope": "session", "key_changes": []},
            "findings": [],
            "suggestions": [{"description": "使用 redis"}],
        },
    ]
    _seed_kb(tmp_path, records)
    with patch("ai_pr_review.knowledge_base.KB_DIR", tmp_path):
        pr = _make_pr(title="Fix login", description="auth")
        diff = _make_diff("src/auth.py")
        ctx = build_similar_reviews_context(pr, diff)
    assert "相似 PR 审查经验" in ctx
    assert "意图" in ctx
    assert "相似度" in ctx


def test_build_similar_reviews_context_empty_when_no_kb(tmp_path):
    with patch("ai_pr_review.knowledge_base.KB_DIR", tmp_path / "noexist"):
        pr = _make_pr()
        diff = _make_diff()
        assert build_similar_reviews_context(pr, diff) == ""


def test_search_similar_respects_top_k(tmp_path):
    records = [
        {"summary": {"intent": f"doc{i}"}, "findings": [{"title": "t"}], "suggestions": []}
        for i in range(5)
    ]
    _seed_kb(tmp_path, records)
    with patch("ai_pr_review.knowledge_base.KB_DIR", tmp_path):
        pr = _make_pr(title="docs")
        diff = _make_diff("README.md")
        results = search_similar_reviews(pr, diff, top_k=2, min_similarity=0.0)
    assert len(results) <= 2
