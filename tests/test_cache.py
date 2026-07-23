"""cache 模块的单元测试"""
import json
import time
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_pr_review.models import (
    AnalysisResult,
    AnalysisSummary,
    Finding,
    Suggestion,
    Severity,
)
from ai_pr_review import cache as cache_mod
from ai_pr_review.cache import (
    _cache_key,
    _serialize_result,
    _deserialize_result,
    get_cached_result,
    save_cached_result,
    clear_cache,
)


# ---------- 测试夹具 ----------

def _make_result() -> AnalysisResult:
    """构造一个完整的 AnalysisResult 用于测试"""
    return AnalysisResult(
        summary=AnalysisSummary(
            intent="Add JWT authentication",
            scope="auth module",
            key_changes=["New auth.py", "Update middleware"],
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
                description="JWT secret hardcoded",
                suggestion="Use env variable",
                code_snippet="secret = 'abc'",
            ),
            Finding(
                type="quality",
                severity=Severity.LOW,
                confidence=2,
                expert="readability",
                file="auth.py",
                line=20,
                title="Missing docstring",
                description="Function lacks docstring",
                suggestion="Add docstring",
                code_snippet="def f(): pass",
            ),
        ],
        suggestions=[
            Suggestion(
                category="security",
                priority=Severity.HIGH,
                description="Move secrets to env vars",
                example="secret = os.environ['JWT_SECRET']",
            ),
        ],
    )


PR_URL = "https://github.com/org/repo/pull/1"
HEAD_SHA = "abcdef1234567890"


# ---------- 测试用例 ----------

def test_cache_key_generation():
    """缓存键应为 pr_url+head_sha 的 sha256 截断（16位），且不同输入产生不同键"""
    key1 = _cache_key(PR_URL, HEAD_SHA)
    key2 = _cache_key(PR_URL, "different_sha")
    key3 = _cache_key("https://github.com/other/repo/pull/2", HEAD_SHA)

    assert len(key1) == 16
    assert key1 != key2
    assert key1 != key3
    # 相同输入应稳定输出同一键
    assert _cache_key(PR_URL, HEAD_SHA) == key1


def test_serialize_deserialize_roundtrip():
    """序列化与反序列化应能完整还原 AnalysisResult"""
    original = _make_result()
    data = _serialize_result(PR_URL, HEAD_SHA, original)
    # 序列化结果应是 JSON 可存储的字典，并包含 cached_at 时间戳
    assert "cached_at" in data
    assert data["pr_url"] == PR_URL
    assert data["head_sha"] == HEAD_SHA
    json.dumps(data)  # 确认可被 JSON 序列化

    restored = _deserialize_result(data)
    assert restored.summary.intent == original.summary.intent
    assert restored.summary.scope == original.summary.scope
    assert restored.summary.key_changes == original.summary.key_changes
    assert len(restored.findings) == len(original.findings)
    for r, o in zip(restored.findings, original.findings):
        assert r.type == o.type
        assert r.severity == o.severity
        assert r.confidence == o.confidence
        assert r.expert == o.expert
        assert r.file == o.file
        assert r.line == o.line
        assert r.title == o.title
        assert r.description == o.description
        assert r.suggestion == o.suggestion
        assert r.code_snippet == o.code_snippet
    assert len(restored.suggestions) == len(original.suggestions)
    for r, o in zip(restored.suggestions, original.suggestions):
        assert r.category == o.category
        assert r.priority == o.priority
        assert r.description == o.description
        assert r.example == o.example


def test_save_and_get_cached_result():
    """保存后应能命中缓存并取回等价结果"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = Path(tmpdir) / "cache"
        with patch.object(cache_mod, "CACHE_DIR", cache_dir):
            result = _make_result()
            save_cached_result(PR_URL, HEAD_SHA, result)

            # 缓存文件应已创建
            expected_path = cache_dir / f"{_cache_key(PR_URL, HEAD_SHA)}.json"
            assert expected_path.exists()

            cached = get_cached_result(PR_URL, HEAD_SHA)
            assert cached is not None
            assert cached.summary.intent == result.summary.intent
            assert len(cached.findings) == len(result.findings)
            assert cached.findings[0].severity == result.findings[0].severity
            assert len(cached.suggestions) == len(result.suggestions)


def test_get_cached_result_miss():
    """不存在的缓存应返回 None"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = Path(tmpdir) / "cache"
        with patch.object(cache_mod, "CACHE_DIR", cache_dir):
            assert get_cached_result(PR_URL, HEAD_SHA) is None


def test_get_cached_result_expired():
    """已过期的缓存应返回 None"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = Path(tmpdir) / "cache"
        with patch.object(cache_mod, "CACHE_DIR", cache_dir):
            result = _make_result()
            save_cached_result(PR_URL, HEAD_SHA, result)

            # 把 cached_at 改为很久以前，模拟过期
            key = _cache_key(PR_URL, HEAD_SHA)
            path = cache_dir / f"{key}.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["cached_at"] = time.time() - 100000  # 远超 TTL
            path.write_text(json.dumps(data), encoding="utf-8")

            # 默认 TTL 下应判定为过期
            assert get_cached_result(PR_URL, HEAD_SHA) is None
            # TTL 设得很大时应能命中
            assert get_cached_result(PR_URL, HEAD_SHA, ttl_seconds=10_000_000) is not None


def test_get_cached_result_no_sha():
    """head_sha 为空时应直接返回 None（不访问文件系统）"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = Path(tmpdir) / "cache"
        with patch.object(cache_mod, "CACHE_DIR", cache_dir):
            assert get_cached_result(PR_URL, "") is None


def test_clear_cache():
    """clear_cache 应清除指定 PR 的缓存条目并返回数量"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = Path(tmpdir) / "cache"
        with patch.object(cache_mod, "CACHE_DIR", cache_dir):
            # 为两个不同 PR 写入缓存
            save_cached_result(PR_URL, HEAD_SHA, _make_result())
            save_cached_result(
                "https://github.com/org/repo/pull/2",
                "sha2222222222222",
                _make_result(),
            )
            # 还有一个不同 PR 但同 URL 的不同 sha
            save_cached_result(PR_URL, "sha9999999999999", _make_result())

            # 清除指定 PR：应删除该 URL 的所有条目（2 条）
            count = clear_cache(PR_URL)
            assert count == 2

            # 该 PR 的缓存应已清空
            assert get_cached_result(PR_URL, HEAD_SHA) is None
            assert get_cached_result(PR_URL, "sha9999999999999") is None
            # 另一个 PR 的缓存应仍存在
            assert get_cached_result(
                "https://github.com/org/repo/pull/2", "sha2222222222222"
            ) is not None

            # 再清除全部
            count = clear_cache()
            assert count == 1


def test_clear_cache_empty():
    """缓存目录不存在或为空时，clear_cache 应返回 0 且不报错"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = Path(tmpdir) / "nonexistent"
        with patch.object(cache_mod, "CACHE_DIR", cache_dir):
            # 目录不存在
            assert clear_cache() == 0
            assert clear_cache(PR_URL) == 0

            # 目录存在但为空
            cache_dir.mkdir()
            assert clear_cache() == 0
            assert clear_cache(PR_URL) == 0
