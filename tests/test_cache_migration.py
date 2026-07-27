"""cache 模块基于 Storage 的迁移与行为测试（T11 [A11]）

覆盖：
- 正常 save/get/clear 通过 Storage 走通
- TTL 过期判断
- 旧 cache 目录一次性迁移
- clear_cache 支持按 pr_url 过滤

注：使用 configure_storage 注入临时 LocalJSONStorage。
"""
import json
import time
from unittest.mock import patch

import pytest

from ai_pr_review.data import cache as cache_mod
from ai_pr_review.data.cache import (
    DEFAULT_TTL_SECONDS,
    _cache_key,
    _deserialize_result,
    _serialize_result,
    clear_cache,
    get_cached_result,
    save_cached_result,
)
from ai_pr_review.core.models import AnalysisResult, AnalysisSummary, Finding, Severity, Suggestion
from ai_pr_review.data.persistence import LocalJSONStorage, configure_storage


def _make_result() -> AnalysisResult:
    return AnalysisResult(
        summary=AnalysisSummary(
            intent="Test intent", scope="test scope", key_changes=["a", "b"],
        ),
        findings=[
            Finding(
                type="security", severity=Severity.HIGH, confidence=4,
                expert="security", file="x.py", line=10, title="t",
                description="d", suggestion="s", code_snippet="c",
            ),
        ],
        suggestions=[
            Suggestion(category="cat", priority=Severity.MEDIUM, description="d", example="e"),
        ],
    )


PR_URL = "https://github.com/owner/repo/pull/1"
HEAD_SHA = "abcdef1234567890"


@pytest.fixture
def storage(tmp_path):
    s = LocalJSONStorage(base_dir=tmp_path / "storage")
    configure_storage(s)
    return s


def test_save_and_get_roundtrip_via_storage(storage):
    result = _make_result()
    save_cached_result(PR_URL, HEAD_SHA, result)

    cached = get_cached_result(PR_URL, HEAD_SHA)
    assert cached is not None
    assert cached.summary.intent == "Test intent"
    assert len(cached.findings) == 1
    assert cached.findings[0].severity == Severity.HIGH
    assert len(cached.suggestions) == 1


def test_ttl_expiry(storage):
    result = _make_result()
    save_cached_result(PR_URL, HEAD_SHA, result)

    # 手动篡改 cached_at 让其过期
    from ai_pr_review.data.storage import Namespace
    key = _cache_key(PR_URL, HEAD_SHA)
    data = storage.get(Namespace.CACHE, key)
    data["cached_at"] = time.time() - 100000
    storage.save(Namespace.CACHE, key, data)

    # 默认 TTL 下应判定为过期
    assert get_cached_result(PR_URL, HEAD_SHA) is None
    # TTL 设大能命中
    assert get_cached_result(PR_URL, HEAD_SHA, ttl_seconds=10_000_000) is not None


def test_get_cached_result_no_sha_returns_none(storage):
    """head_sha 为空时直接返回 None，不查 Storage"""
    assert get_cached_result(PR_URL, "") is None


def test_get_cached_result_miss(storage):
    """未缓存时返回 None"""
    assert get_cached_result(PR_URL, HEAD_SHA) is None


def test_clear_cache_all(storage):
    save_cached_result(PR_URL, HEAD_SHA, _make_result())
    save_cached_result("https://github.com/other/2", "sha2", _make_result())

    count = clear_cache()
    assert count == 2
    assert get_cached_result(PR_URL, HEAD_SHA) is None
    assert get_cached_result("https://github.com/other/2", "sha2") is None


def test_clear_cache_by_pr_url(storage):
    save_cached_result(PR_URL, HEAD_SHA, _make_result())
    save_cached_result(PR_URL, "sha999", _make_result())
    save_cached_result("https://github.com/other/2", "sha2", _make_result())

    count = clear_cache(PR_URL)
    assert count == 2
    assert get_cached_result(PR_URL, HEAD_SHA) is None
    assert get_cached_result(PR_URL, "sha999") is None
    assert get_cached_result("https://github.com/other/2", "sha2") is not None


def test_old_cache_dir_migrates_on_first_read(tmp_path):
    """旧 ~/.ai-pr-review/cache/*.json 首次 get 时迁移到 Storage"""
    # 构造旧 cache 目录
    with patch.object(cache_mod, "_OLD_CACHE_DIR", tmp_path / "old_cache"):
        old_dir = tmp_path / "old_cache"
        old_dir.mkdir()

        # 写入一个旧缓存文件
        data = _serialize_result(PR_URL, HEAD_SHA, _make_result())
        key = _cache_key(PR_URL, HEAD_SHA)
        old_file = old_dir / f"{key}.json"
        old_file.write_text(json.dumps(data), encoding="utf-8")

        configure_storage(LocalJSONStorage(base_dir=tmp_path / "storage"))

        # 首次 get_cached_result 应触发迁移
        cached = get_cached_result(PR_URL, HEAD_SHA)
        assert cached is not None
        assert cached.summary.intent == "Test intent"


def test_old_cache_files_not_deleted_after_migration(tmp_path):
    """迁移后旧文件应保留"""
    with patch.object(cache_mod, "_OLD_CACHE_DIR", tmp_path / "old_cache"):
        old_dir = tmp_path / "old_cache"
        old_dir.mkdir()
        data = _serialize_result(PR_URL, HEAD_SHA, _make_result())
        key = _cache_key(PR_URL, HEAD_SHA)
        old_file = old_dir / f"{key}.json"
        old_file.write_text(json.dumps(data), encoding="utf-8")

        configure_storage(LocalJSONStorage(base_dir=tmp_path / "storage"))
        get_cached_result(PR_URL, HEAD_SHA)

        assert old_file.exists()


def test_clear_cache_empty_storage(storage):
    """空 Storage 上 clear_cache 返回 0"""
    assert clear_cache() == 0
    assert clear_cache(PR_URL) == 0


def test_serialize_deserialize_roundtrip_preserves_fields():
    """_serialize_result 与 _deserialize_result 完整互逆"""
    original = _make_result()
    data = _serialize_result(PR_URL, HEAD_SHA, original)
    restored = _deserialize_result(data)
    assert restored.summary.intent == original.summary.intent
    assert restored.summary.scope == original.summary.scope
    assert restored.summary.key_changes == original.summary.key_changes
    assert len(restored.findings) == len(original.findings)
    for r, o in zip(restored.findings, original.findings):
        assert r.severity == o.severity
        assert r.file == o.file
        assert r.title == o.title
    assert len(restored.suggestions) == len(original.suggestions)