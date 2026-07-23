"""AI 不可用时的分级降级管理模块

设计目标：
- 单例 DegradationManager 跟踪连续失败次数，映射到 4 级降级策略
- Level 0：正常工作；Level 1：返回过期缓存；Level 2：返回空结果；Level 3：拒绝服务
- 所有降级事件以结构化 warning 日志记录，便于监控告警
"""
import logging
from typing import Optional

from ai_pr_review.models import AnalysisResult, AnalysisSummary

logger = logging.getLogger(__name__)

# 各级别触发阈值（连续失败次数）
LEVEL1_THRESHOLD = 5  # 缓存降级
LEVEL2_THRESHOLD = 10  # 空结果降级
LEVEL3_THRESHOLD = 15  # 拒绝服务

# 用于"忽略 TTL"的极大值，使任何过期缓存都被视为有效
_IGNORE_TTL = 10 ** 18


class DegradationManager:
    """AI 不可用时的分级降级管理器（单例）

    级别判定（基于 _consecutive_failures）：
      < 5   -> Level 0（正常）
      5-9   -> Level 1（返回过期缓存）
      10-14 -> Level 2（返回空结果）
      >= 15 -> Level 3（拒绝服务）
    """

    _instance: Optional["DegradationManager"] = None

    def __new__(cls):
        # 单例：首次构造时初始化状态字段
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._consecutive_failures = 0
        return cls._instance

    def record_failure(self, pr_url: str = "") -> None:
        """记录一次 AI 调用失败，失败计数自增并写日志"""
        self._consecutive_failures += 1
        level = self.current_level()
        logger.warning(
            "AI call failure recorded",
            extra={"pr_url": pr_url, "failures": self._consecutive_failures, "level": level},
        )

    def record_success(self) -> None:
        """记录一次 AI 调用成功，重置失败计数"""
        self._consecutive_failures = 0

    def current_level(self) -> int:
        """返回当前降级级别：0=正常, 1=缓存, 2=空结果, 3=拒绝"""
        if self._consecutive_failures < LEVEL1_THRESHOLD:
            return 0
        if self._consecutive_failures < LEVEL2_THRESHOLD:
            return 1
        if self._consecutive_failures < LEVEL3_THRESHOLD:
            return 2
        return 3

    def reset(self) -> None:
        """重置状态（测试用）"""
        self._consecutive_failures = 0

    def get_degraded_result(
        self,
        pr_url: str,
        sha: str = "",
        reason: str = "",
    ) -> Optional[AnalysisResult]:
        """根据当前降级级别返回降级结果

        Level 1: 尝试返回过期缓存（忽略 TTL）；缓存不存在则降级到 Level 2 行为
        Level 2: 返回空 AnalysisResult，summary 标注 [降级模式]
        Level 3: 返回 None（调用方应返回 503）
        Level 0: 返回 None（不应被调用）
        """
        level = self.current_level()

        if level == 1:
            # 延迟导入避免循环依赖，且便于在测试中 mock
            from ai_pr_review.cache import get_cached_result

            cached = get_cached_result(pr_url, sha, ttl_seconds=_IGNORE_TTL)
            if cached is not None:
                # 在 summary.intent 前加降级标记，保留原始分析内容
                cached.summary.intent = f"[降级模式-缓存] {cached.summary.intent}"
                logger.warning(
                    "Degrading to cached result",
                    extra={"pr_url": pr_url, "level": level, "reason": reason},
                )
                return cached
            # 缓存不存在，按 Level 2 处理
            return self._build_empty_result(pr_url, reason, level=2)

        if level == 2:
            return self._build_empty_result(pr_url, reason, level=2)

        if level >= 3:
            logger.warning(
                "Service unavailable due to degradation",
                extra={"pr_url": pr_url, "level": level, "reason": reason},
            )
            return None

        # Level 0：正常状态，不应被调用
        return None

    def _build_empty_result(
        self, pr_url: str, reason: str, level: int
    ) -> AnalysisResult:
        """构造空 AnalysisResult（Level 2 降级结果）"""
        logger.warning(
            "Degrading to empty result",
            extra={"pr_url": pr_url, "level": level, "reason": reason},
        )
        return AnalysisResult(
            summary=AnalysisSummary(
                intent=f"[降级模式] AI 服务暂时不可用，已跳过深度分析。原因：{reason}",
                scope="degraded",
                key_changes=[],
            ),
            findings=[],
            suggestions=[],
        )


def get_degradation_manager() -> DegradationManager:
    """获取 DegradationManager 单例的工厂函数"""
    return DegradationManager()
