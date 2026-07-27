"""轻量 Metrics 收集模块 — Counter / Histogram / Gauge + 单例 Registry

设计目标：
- 纯标准库实现，无第三方依赖
- Registry 单例模式，全局共享指标实例
- snapshot 方法返回纯 dict/list 结构，可被 json.dumps 序列化
- 线程安全暂不考虑（asyncio 单线程环境）

注：本模块仅用于进程内观测，不直接对接 Prometheus 等外部系统。
"""
import json
from collections import defaultdict
from typing import Optional


class Counter:
    """计数器指标 — 单调递增（理论上），按 label 组合分别累计"""

    def __init__(self, name: str, description: str = "", labels: tuple[str, ...] = ()):
        self.name = name
        self.description = description
        self.label_names = labels
        # 用 defaultdict 简化未初始化 label 组合的访问
        self._values: dict[tuple, float] = defaultdict(float)

    def inc(self, value: float = 1.0, **labels) -> None:
        """自增计数器，labels 必须与 label_names 完全匹配"""
        self._validate_labels(labels)
        key = self._labels_key(labels)
        self._values[key] += value

    def get(self, **labels) -> float:
        """获取指定 label 组合的当前值"""
        self._validate_labels(labels)
        key = self._labels_key(labels)
        return self._values[key]

    def snapshot(self) -> list[dict]:
        """返回 [{"name": ..., "labels": {...}, "value": ...}, ...]"""
        return [
            {"name": self.name, "labels": dict(zip(self.label_names, key)), "value": value}
            for key, value in self._values.items()
        ]

    def _validate_labels(self, labels: dict) -> None:
        """校验传入的 label keys 与声明的 label_names 一致"""
        provided = set(labels.keys())
        expected = set(self.label_names)
        if provided != expected:
            raise ValueError(
                f"Counter '{self.name}' labels mismatch: "
                f"expected {sorted(expected)}, got {sorted(provided)}"
            )

    def _labels_key(self, labels: dict) -> tuple:
        """将 labels dict 转为按 label_names 顺序排列的 tuple，作为内部 key"""
        return tuple(labels[name] for name in self.label_names)


class Histogram:
    """直方图指标 — 按预设分桶统计观测值分布"""

    # 默认分桶（参考 Prometheus 默认值）
    DEFAULT_BUCKETS = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10]

    def __init__(self, name: str, description: str = "", buckets: list[float] | None = None):
        self.name = name
        self.description = description
        self.buckets = buckets if buckets is not None else list(self.DEFAULT_BUCKETS)
        # 每个桶的累计计数（value <= bucket_le 的观测数）
        self._counts: list[int] = [0] * len(self.buckets)
        self._sum: float = 0.0  # 所有观测值总和
        self._count: int = 0  # 总观测次数

    def observe(self, value: float) -> None:
        """记录一个观测值，更新所有满足 value <= bucket_le 的桶计数"""
        self._sum += value
        self._count += 1
        for i, bucket_le in enumerate(self.buckets):
            if value <= bucket_le:
                self._counts[i] += 1

    def snapshot(self) -> dict:
        """返回 {"name": ..., "buckets": [{"le": ..., "count": N}, ...], "sum": ..., "count": ...}"""
        return {
            "name": self.name,
            "buckets": [
                {"le": bucket_le, "count": count}
                for bucket_le, count in zip(self.buckets, self._counts)
            ],
            "sum": self._sum,
            "count": self._count,
        }


class Gauge:
    """仪表指标 — 可增可减的当前值"""

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self._value: float = 0.0

    def set(self, value: float) -> None:
        """设置当前值"""
        self._value = value

    def inc(self, value: float = 1.0) -> None:
        """自增"""
        self._value += value

    def dec(self, value: float = 1.0) -> None:
        """自减"""
        self._value -= value

    def get(self) -> float:
        """获取当前值"""
        return self._value

    def snapshot(self) -> dict:
        """返回 {"name": ..., "value": ...}"""
        return {"name": self.name, "value": self._value}


class MetricsRegistry:
    """指标注册中心 — 单例，统一管理 Counter/Histogram/Gauge 实例"""

    _instance: Optional["MetricsRegistry"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._counters = {}
            cls._instance._histograms = {}
            cls._instance._gauges = {}
        return cls._instance

    def counter(self, name: str, description: str = "", labels: tuple[str, ...] = ()) -> Counter:
        """获取或创建 Counter（同名复用，描述与 labels 仅在首次创建时生效）"""
        if name not in self._counters:
            self._counters[name] = Counter(name, description, labels)
        return self._counters[name]

    def histogram(self, name: str, description: str = "", buckets: list[float] | None = None) -> Histogram:
        """获取或创建 Histogram（同名复用）"""
        if name not in self._histograms:
            self._histograms[name] = Histogram(name, description, buckets)
        return self._histograms[name]

    def gauge(self, name: str, description: str = "") -> Gauge:
        """获取或创建 Gauge（同名复用）"""
        if name not in self._gauges:
            self._gauges[name] = Gauge(name, description)
        return self._gauges[name]

    def snapshot(self) -> dict:
        """返回 {"counters": [...], "histograms": [...], "gauges": [...]} 的 JSON 可序列化结构

        注：Counter.snapshot 返回 list[dict]（按 label 组合展开），需展平后合并。
        """
        counters: list[dict] = []
        for c in self._counters.values():
            counters.extend(c.snapshot())
        return {
            "counters": counters,
            "histograms": [h.snapshot() for h in self._histograms.values()],
            "gauges": [g.snapshot() for g in self._gauges.values()],
        }

    def snapshot_json(self) -> str:
        """返回 json.dumps(snapshot(), ensure_ascii=False, indent=2)"""
        return json.dumps(self.snapshot(), ensure_ascii=False, indent=2)

    def reset(self) -> None:
        """清空所有指标（测试用，避免单例状态在测试间相互污染）"""
        self._counters.clear()
        self._histograms.clear()
        self._gauges.clear()


def get_registry() -> MetricsRegistry:
    """获取 MetricsRegistry 单例"""
    return MetricsRegistry()
