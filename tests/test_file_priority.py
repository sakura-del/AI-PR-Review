"""file_priority 模块的单元测试"""
from ai_pr_review.models import FileDiff, ChangeType
from ai_pr_review.file_priority import (
    _detect_file_type,
    calculate_priority_score,
    sort_files_by_priority,
    get_priority_summary,
    FILE_TYPE_WEIGHTS,
)


def _make_file_diff(
    path: str,
    additions: int = 0,
    deletions: int = 0,
    is_binary: bool = False,
    is_generated: bool = False,
) -> FileDiff:
    """构造测试用 FileDiff 实例"""
    return FileDiff(
        path=path,
        change_type=ChangeType.MODIFIED,
        hunks=[],
        additions=additions,
        deletions=deletions,
        is_binary=is_binary,
        is_generated=is_generated,
    )


def test_detect_file_type_source():
    """源码文件应被识别为 source 类型"""
    for path in ["src/main.py", "app/handler.js", "service/user.go", "Api.java"]:
        fd = _make_file_diff(path)
        assert _detect_file_type(fd) == "source", f"路径 {path} 应识别为 source"


def test_detect_file_type_test():
    """测试文件应被识别为 test 类型"""
    for path in ["tests/test_main.py", "src/app.test.js", "handler_spec.go", "pkg/__tests__/a.ts"]:
        fd = _make_file_diff(path)
        assert _detect_file_type(fd) == "test", f"路径 {path} 应识别为 test"


def test_detect_file_type_config():
    """配置文件应被识别为 config 类型"""
    for path in ["config.yaml", "app.toml", "package.json", "settings.ini"]:
        fd = _make_file_diff(path)
        assert _detect_file_type(fd) == "config", f"路径 {path} 应识别为 config"


def test_detect_file_type_binary():
    """二进制文件应被识别为 binary 类型，优先于扩展名判断"""
    # 即使路径以 .py 结尾，is_binary=True 也应优先返回 binary
    fd = _make_file_diff("src/main.py", is_binary=True)
    assert _detect_file_type(fd) == "binary"


def test_detect_file_type_generated():
    """生成文件应被识别为 generated 类型，优先于扩展名判断"""
    fd = _make_file_diff("src/generated.go", is_generated=True)
    assert _detect_file_type(fd) == "generated"


def test_detect_file_type_doc():
    """文档文件应被识别为 doc 类型"""
    for path in ["README.md", "docs/guide.rst", "notes.txt"]:
        fd = _make_file_diff(path)
        assert _detect_file_type(fd) == "doc", f"路径 {path} 应识别为 doc"


def test_calculate_priority_score_source_high():
    """源码文件得分应高于测试文件，且包含核心路径时分数更高"""
    source = _make_file_diff("src/api/handler.py", additions=100, deletions=20)
    score = calculate_priority_score(source)

    # 源码类型分 = 1.0 * 0.4 = 0.4
    # 变更规模：log10(120) ≈ 2.08，size_score = min(1.0, 2.08/2.0) = 1.0，权重 = 0.3
    # 核心路径：包含 src/api/handler，+0.2
    # 路径深度：2 层，depth_score = 0.7，权重 = 0.07
    # 总分约为 0.4 + 0.3 + 0.2 + 0.07 = 0.97
    assert score > 0.8, f"源码核心文件得分应较高，实际: {score}"
    assert score <= 1.0

    # 验证源码文件分数高于同规模的测试文件
    test_file = _make_file_diff("tests/test_handler.py", additions=100, deletions=20)
    test_score = calculate_priority_score(test_file)
    assert score > test_score


def test_calculate_priority_score_generated_zero():
    """生成文件的类型权重为 0，结合深路径和零变更，总得分应为 0"""
    # 路径深度 7 层：depth_score = max(0, 1.0 - 7*0.15) = 0
    # 类型权重 0、变更规模 0、无核心路径
    # 总分 = 0
    generated = _make_file_diff(
        "a/b/c/d/e/f/g/generated.go",
        additions=0,
        deletions=0,
        is_generated=True,
    )
    score = calculate_priority_score(generated)
    assert score == 0.0, f"生成文件深度路径零变更应得 0 分，实际: {score}"

    # 验证 FILE_TYPE_WEIGHTS 中 generated 权重为 0
    assert FILE_TYPE_WEIGHTS["generated"] == 0.0


def test_calculate_priority_score_binary_zero():
    """二进制文件的类型权重为 0，结合深路径和零变更，总得分应为 0"""
    binary = _make_file_diff(
        "a/b/c/d/e/f/g/image.png",
        additions=0,
        deletions=0,
        is_binary=True,
    )
    score = calculate_priority_score(binary)
    assert score == 0.0
    assert FILE_TYPE_WEIGHTS["binary"] == 0.0


def test_calculate_priority_score_shallow_path_higher():
    """路径越浅的文件得分应越高（其他条件相同时）"""
    shallow = _make_file_diff("main.py", additions=10, deletions=0)
    deep = _make_file_diff("a/b/c/d/e/main.py", additions=10, deletions=0)
    score_shallow = calculate_priority_score(shallow)
    score_deep = calculate_priority_score(deep)
    assert score_shallow > score_deep


def test_calculate_priority_score_within_range():
    """所有文件的优先级分数应在 [0.0, 1.0] 范围内"""
    files = [
        _make_file_diff("src/core/api.py", additions=500, deletions=200),
        _make_file_diff("tests/test_x.py", additions=50, deletions=10),
        _make_file_diff("config.yaml", additions=5, deletions=0),
        _make_file_diff("README.md", additions=10, deletions=2),
        _make_file_diff("a/b/c/d/e/f/g/h.txt", additions=0, deletions=0, is_generated=True),
    ]
    for f in files:
        score = calculate_priority_score(f)
        assert 0.0 <= score <= 1.0, f"路径 {f.path} 分数 {score} 越界"


def test_sort_files_by_priority():
    """排序后高分文件应在前，低分文件在后"""
    files = [
        _make_file_diff("README.md", additions=5, deletions=0),              # 文档，低分
        _make_file_diff("src/api/handler.py", additions=100, deletions=20),  # 源码+核心路径，高分
        _make_file_diff("config.yaml", additions=10, deletions=0),           # 配置，中低分
        _make_file_diff("tests/test_handler.py", additions=50, deletions=5), # 测试，中分
    ]
    sorted_files = sort_files_by_priority(files)

    # 排序后第一个应是源码核心文件
    assert sorted_files[0].path == "src/api/handler.py"
    # 最后一个应是文档（最低分）
    assert sorted_files[-1].path == "README.md"

    # 验证分数严格非递增
    scores = [calculate_priority_score(f) for f in sorted_files]
    for i in range(len(scores) - 1):
        assert scores[i] >= scores[i + 1]


def test_sort_files_by_priority_empty():
    """空列表排序应返回空列表"""
    assert sort_files_by_priority([]) == []


def test_sort_files_by_priority_preserves_count():
    """排序后文件数量应保持不变"""
    files = [
        _make_file_diff(f"file_{i}.py", additions=10, deletions=5)
        for i in range(5)
    ]
    sorted_files = sort_files_by_priority(files)
    assert len(sorted_files) == len(files)


def test_get_priority_summary():
    """优先级摘要应包含正确的字段并按分数降序排列"""
    files = [
        _make_file_diff("src/main.py", additions=100, deletions=10),
        _make_file_diff("tests/test_main.py", additions=20, deletions=5),
        _make_file_diff("config.yaml", additions=3, deletions=0),
    ]
    summary = get_priority_summary(files)

    # 字段完整性检查
    assert len(summary) == len(files)
    for item in summary:
        assert set(item.keys()) == {"path", "type", "score", "changes"}

    # 验证字段值正确
    by_path = {item["path"]: item for item in summary}
    assert by_path["src/main.py"]["type"] == "source"
    assert by_path["tests/test_main.py"]["type"] == "test"
    assert by_path["config.yaml"]["type"] == "config"
    assert by_path["src/main.py"]["changes"] == 110
    assert by_path["config.yaml"]["changes"] == 3

    # 验证按分数降序排列
    scores = [item["score"] for item in summary]
    for i in range(len(scores) - 1):
        assert scores[i] >= scores[i + 1]

    # 源码文件应排在最前
    assert summary[0]["path"] == "src/main.py"


def test_get_priority_summary_empty():
    """空列表的摘要应为空列表"""
    assert get_priority_summary([]) == []
