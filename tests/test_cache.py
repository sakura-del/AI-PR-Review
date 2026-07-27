"""cache 模块测试（v0.9 适配版 — 基于 Storage）

v0.9 重构后，cache.py 通过 persistence.Storage 抽象读写数据。
本测试：
- 用 configure_storage + LocalJSONStorage 注入临时存储
- 保留序列化/反序列化纯函数测试
- 替换旧的"patch CACHE_DIR + 检查文件存在"为"通过公共 API 验证行为"
"""
import time

import pytest

from ai_pr_review.data.cache import (
    _cache_key,
    _deserialize_result,
    _serialize_result,
    clear_cache,
    get_cached_result,
    save_cached_result,
)
from ai_pr_review.core.models import (
    AnalysisResult,
    AnalysisSummary,
    Finding,
    Severity,
    Suggestion,
)
from ai_pr_review.data.persistence import LocalJSONStorage, configure_storage


def _make_result() -> AnalysisResult:
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


@pytest.fixture
def storage(tmp_path):
    s = LocalJSONStorage(base_dir=tmp_path / "storage")
    configure_storage(s)
    return s


# ===== 纯函数测试（不依赖 Storage）=====

def test_cache_key_generation():
    key1 = _cache_key(PR_URL, HEAD_SHA)
    key2 = _cache_key(PR_URL, "different_sha")
    key3 = _cache_key("https://github.com/other/repo/pull/2", HEAD_SHA)

    assert len(key1) == 16
    assert key1 != key2
    assert key1 != key3
    assert _cache_key(PR_URL, HEAD_SHA) == key1


def test_serialize_deserialize_roundtrip():
    original = _make_result()
    data = _serialize_result(PR_URL, HEAD_SHA, original)
    assert "cached_at" in data
    assert data["pr_url"] == PR_URL
    assert data["head_sha"] == HEAD_SHA
    import json
    json.dumps(data)

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


# ===== 通过 Storage 的行为测试 =====

def test_save_and_get_cached_result(storage):
    result = _make_result()
    save_cached_result(PR_URL, HEAD_SHA, result)
    cached = get_cached_result(PR_URL, HEAD_SHA)
    assert cached is not None
    assert cached.summary.intent == result.summary.intent
    assert len(cached.findings) == len(result.findings)
    assert cached.findings[0].severity == result.findings[0].severity


def test_get_cached_result_miss(storage):
    assert get_cached_result(PR_URL, HEAD_SHA) is None


def test_get_cached_result_expired(storage):
    """已过期的缓存应返回 None"""
    from ai_pr_review.data.storage import Namespace
    result = _make_result()
    save_cached_result(PR_URL, HEAD_SHA, result)

    # 手动把 cached_at 改为很久以前
    key = _cache_key(PR_URL, HEAD_SHA)
    data = storage.get(Namespace.CACHE, key)
    data["cached_at"] = time.time() - 100000
    storage.save(Namespace.CACHE, key, data)

    assert get_cached_result(PR_URL, HEAD_SHA) is None
    assert get_cached_result(PR_URL, HEAD_SHA, ttl_seconds=10_000_000) is not None


def test_get_cached_result_no_sha(storage):
    """head_sha 为空时直接返回 None"""
    assert get_cached_result(PR_URL, "") is None


def test_clear_cache_by_pr_url(storage):
    save_cached_result(PR_URL, HEAD_SHA, _make_result())
    save_cached_result(PR_URL, "sha9999999999999", _make_result())
    save_cached_result("https://github.com/org/repo/pull/2", "sha2222222222222", _make_result())

    count = clear_cache(PR_URL)
    assert count == 2
    assert get_cached_result(PR_URL, HEAD_SHA) is None
    assert get_cached_result(PR_URL, "sha9999999999999") is None
    assert get_cached_result("https://github.com/org/repo/pull/2", "sha2222222222222") is not None

    # 再清除全部
    count = clear_cache()
    assert count == 1


def test_clear_cache_empty_storage(storage):
    assert clear_cache() == 0
    assert clear_cache(PR_URL) == 0


# ===== 向后兼容：CACHE_DIR 常量 =====

def test_cache_dir_constant_preserved():
    """CACHE_DIR 常量保留供外部 import"""
    from ai_pr_review.data.cache import CACHE_DIR
    assert CACHE_DIR.name == "cache"


# ===== 兼容旧 import：cache_mod.CACHE_DIR =====

def test_old_module_attribute_still_exists():
    import ai_pr_review.data.cache as cache_mod
    assert hasattr(cache_mod, "CACHE_DIR")
    assert cache_mod.CACHE_DIR.name == "cache"