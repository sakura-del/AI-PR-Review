"""pytest 全局 fixtures 与 Storage 隔离

所有测试自动获得：
1. 重置的 Storage 单例
2. 注入到 tmp_path 的默认 LocalJSONStorage（防止写入用户真实 ~/.ai-pr-review/）
3. 重定向到空 tmp 子目录的旧文件/目录路径（防止迁移读取用户真实数据）

需要特定 Storage 的测试可通过 configure_storage() 显式覆盖默认。
"""
from unittest.mock import patch

import pytest

from ai_pr_review.data import cache as cache_mod
from ai_pr_review.data import history as history_mod
from ai_pr_review.data import team_rules as team_rules_mod
from ai_pr_review.data.persistence import LocalJSONStorage, configure_storage, reset_storage


@pytest.fixture(autouse=True)
def _isolate_storage_and_legacy_paths(tmp_path):
    """每个测试前后隔离 Storage 与旧路径

    autouse=True：自动应用于所有测试，无需显式声明。
    """
    # 重置 Storage 单例并注入默认临时存储
    reset_storage()
    default_storage = LocalJSONStorage(base_dir=tmp_path / "storage")
    configure_storage(default_storage)

    # 把所有迁移源（历史/缓存/团队规则）重定向到空的 tmp 子目录
    with patch.object(history_mod, "_OLD_HISTORY_FILE", tmp_path / "old_history.json"), \
         patch.object(cache_mod, "_OLD_CACHE_DIR", tmp_path / "old_cache"), \
         patch.object(team_rules_mod, "_OLD_TEAM_RULES_DIR", tmp_path / "old_team_rules"):
        yield default_storage

    reset_storage()