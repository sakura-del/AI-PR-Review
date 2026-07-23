"""智能文件优先级排序 — 让核心业务文件优先进入 AI 上下文"""
import math
import re
import logging
from ai_pr_review.models import FileDiff

logger = logging.getLogger(__name__)

# 文件类型权重
FILE_TYPE_WEIGHTS = {
    "source": 1.0,      # .py .js .ts .go .java .rs .c .cpp
    "test": 0.5,        # test_*.py *_test.go *.test.js
    "config": 0.3,      # .yaml .yml .toml .json .ini .cfg
    "doc": 0.1,         # .md .rst .txt
    "generated": 0.0,   # lock 文件、生成文件
    "binary": 0.0,      # 图片、二进制
}

# 关键词模式（出现在文件路径中表明可能是核心文件）
CORE_PATH_PATTERNS = [
    re.compile(r"(src|core|main|app|api|model|service|controller|handler)", re.IGNORECASE),
    re.compile(r"(router|route|endpoint|view|schema|domain)", re.IGNORECASE),
]

# 测试文件模式
TEST_PATTERNS = [
    re.compile(r"(test_|_test\.|\.test\.|spec\.|__tests__)", re.IGNORECASE),
]

# 源码扩展名
SOURCE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs",
    ".go", ".java", ".rs", ".c", ".cpp", ".h", ".hpp",
    ".rb", ".php", ".swift", ".kt", ".scala",
}

# 配置文件扩展名
CONFIG_EXTENSIONS = {".yaml", ".yml", ".toml", ".json", ".ini", ".cfg", ".env"}

# 文档扩展名
DOC_EXTENSIONS = {".md", ".rst", ".txt"}


def _detect_file_type(file_diff: FileDiff) -> str:
    """检测文件类型"""
    if file_diff.is_binary:
        return "binary"
    if file_diff.is_generated:
        return "generated"

    path = file_diff.path.lower()

    # 检查测试文件
    for pattern in TEST_PATTERNS:
        if pattern.search(path):
            return "test"

    # 检查扩展名
    for ext in SOURCE_EXTENSIONS:
        if path.endswith(ext):
            return "source"
    for ext in CONFIG_EXTENSIONS:
        if path.endswith(ext):
            return "config"
    for ext in DOC_EXTENSIONS:
        if path.endswith(ext):
            return "doc"

    return "source"  # 默认当作源码


def _has_core_pattern(path: str) -> bool:
    """检查路径是否包含核心业务关键词"""
    for pattern in CORE_PATH_PATTERNS:
        if pattern.search(path):
            return True
    return False


def calculate_priority_score(file_diff: FileDiff) -> float:
    """计算文件优先级分数（0.0 - 1.0，越高越优先）

    评分维度：
    - 文件类型权重（40%）：源码 > 测试 > 配置 > 文档
    - 变更规模（30%）：变更行数越多越重要
    - 核心路径（20%）：路径包含 src/core/api 等关键词加分
    - 路径深度（10%）：越浅的文件越可能是核心文件
    """
    score = 0.0

    # 文件类型权重（40%）
    file_type = _detect_file_type(file_diff)
    type_weight = FILE_TYPE_WEIGHTS.get(file_type, 0.5)
    score += type_weight * 0.4

    # 变更规模（30%）：变更行数归一化
    # 用 log 缩放，避免大文件垄断
    change_lines = file_diff.additions + file_diff.deletions
    size_score = min(1.0, math.log10(max(1, change_lines)) / 2.0)
    score += size_score * 0.3

    # 核心路径（20%）
    if _has_core_pattern(file_diff.path):
        score += 0.2

    # 路径深度（10%）：路径越浅分数越高
    depth = file_diff.path.count("/")
    depth_score = max(0.0, 1.0 - depth * 0.15)
    score += depth_score * 0.1

    return round(score, 3)


def sort_files_by_priority(files: list[FileDiff]) -> list[FileDiff]:
    """按优先级分数降序排序文件列表"""
    scored = [(f, calculate_priority_score(f)) for f in files]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [f for f, _ in scored]


def get_priority_summary(files: list[FileDiff]) -> list[dict]:
    """获取文件优先级摘要（用于调试和展示）"""
    result = []
    for f in files:
        result.append({
            "path": f.path,
            "type": _detect_file_type(f),
            "score": calculate_priority_score(f),
            "changes": f.additions + f.deletions,
        })
    result.sort(key=lambda x: x["score"], reverse=True)
    return result
