"""impact_graph 模块测试 — 覆盖闭包遍历、深度限制、上下文构建"""
import pytest
from ai_pr_review.impact_graph import (
    _collect_all_calls,
    _collect_all_callers,
    _bfs_closure,
    build_impact_subgraph,
    build_impact_graph_context,
)
from ai_pr_review.models import (
    ParsedDiff,
    FileDiff,
    DiffHunk,
    ChangeType,
)


def _make_hunk(file_path: str, content: str) -> DiffHunk:
    return DiffHunk(
        file_path=file_path,
        change_type=ChangeType.MODIFIED,
        old_start=1, old_count=1,
        new_start=1, new_count=1,
        content=content,
        header="@@ -1,1 +1,1 @@",
    )


def _make_file(path: str, content: str) -> FileDiff:
    return FileDiff(
        path=path,
        change_type=ChangeType.MODIFIED,
        hunks=[_make_hunk(path, content)],
        additions=1,
        deletions=1,
    )


# ===== _collect_all_calls / _collect_all_callers 单元测试 =====

def test_collect_calls_basic():
    code = "def a():\n    b()\n    c()\ndef b():\n    d()\n"
    calls = _collect_all_calls(code)
    assert calls["a"] == ["b", "c"]
    assert calls["b"] == ["d"]


def test_collect_calls_async_function():
    code = "async def fetch():\n    await load()\n"
    calls = _collect_all_calls(code)
    assert "fetch" in calls
    assert "load" in calls["fetch"]


def test_collect_calls_syntax_error_returns_empty():
    calls = _collect_all_calls("def broken(:\n")
    assert calls == {}


def test_collect_callers_basic():
    code = "def a():\n    b()\ndef b():\n    c()\ndef c():\n    pass\n"
    callers = _collect_all_callers(code)
    # b 被 a 调用，c 被 b 调用
    assert "a" in callers["b"]
    assert "b" in callers["c"]


def test_collect_callers_no_callers():
    code = "def lonely():\n    pass\n"
    callers = _collect_all_callers(code)
    assert callers.get("lonely", []) == []


# ===== _bfs_closure 单元测试 =====

def test_bfs_closure_depth_limit():
    # a→b→c→d 链
    edges = {"a": ["b"], "b": ["c"], "c": ["d"], "d": []}
    # 深度 1：仅 b
    result = _bfs_closure(["a"], edges, max_depth=1, max_per_level=10)
    assert result["a"] == ["b"]
    # 深度 2：b, c
    result = _bfs_closure(["a"], edges, max_depth=2, max_per_level=10)
    assert result["a"] == ["b", "c"]
    # 深度 3：b, c, d
    result = _bfs_closure(["a"], edges, max_depth=3, max_per_level=10)
    assert result["a"] == ["b", "c", "d"]


def test_bfs_closure_max_per_level():
    # 扇出节点
    edges = {"root": ["a", "b", "c", "d", "e"]}
    result = _bfs_closure(["root"], edges, max_depth=1, max_per_level=2)
    # 每层只取前 2 个
    assert len(result["root"]) == 2


def test_bfs_closure_no_cycle_infinite_loop():
    # 循环依赖：a↔b
    edges = {"a": ["b"], "b": ["a"]}
    result = _bfs_closure(["a"], edges, max_depth=5, max_per_level=10)
    # 访问集合去重，结果应有限
    assert "b" in result["a"]
    assert len(result["a"]) <= 2


def test_bfs_closure_start_not_in_map():
    result = _bfs_closure(["ghost"], {}, max_depth=2, max_per_level=5)
    assert result["ghost"] == []


# ===== build_impact_subgraph 集成测试 =====

def test_build_impact_subgraph_two_level_closure():
    code = (
        "def caller_a():\n"
        "    target()\n"
        "def target():\n"
        "    helper()\n"
        "def helper():\n"
        "    util()\n"
        "def util():\n"
        "    pass\n"
    )
    subgraph = build_impact_subgraph(code, ["target"], max_depth=2)
    # callees: target → helper → util（深度 2，到 helper 为止）
    assert "helper" in subgraph["callees"]["target"]
    # callers: target ← caller_a（深度 1）
    assert "caller_a" in subgraph["callers"]["target"]


def test_build_impact_subgraph_empty_functions():
    subgraph = build_impact_subgraph("def x():\n    pass\n", [])
    assert subgraph == {"callers": {}, "callees": {}}


def test_build_impact_subgraph_syntax_error_safe():
    subgraph = build_impact_subgraph("def broken(:", ["broken"])
    # 不抛异常，返回空闭包
    assert subgraph["callers"].get("broken", []) == []
    assert subgraph["callees"].get("broken", []) == []


# ===== build_impact_graph_context 端到端测试 =====

def test_build_impact_graph_context_with_changed_function():
    """模拟变更函数 + 拉取文件内容，验证上下文输出"""
    diff_content = "+def target():\n+    helper()\n"
    parsed = ParsedDiff(
        files=[_make_file("src/mod.py", diff_content)],
        total_additions=2,
        total_deletions=0,
    )
    file_content = (
        "def caller_a():\n"
        "    target()\n"
        "def target():\n"
        "    helper()\n"
        "def helper():\n"
        "    pass\n"
    )

    def fake_get(url, path, ref):
        return file_content

    ctx = build_impact_graph_context(parsed, fake_get, "repo", "ref")
    assert "增量影响图" in ctx
    assert "src/mod.py" in ctx
    assert "target" in ctx
    assert "caller_a" in ctx  # callers
    assert "helper" in ctx    # callees


def test_build_impact_graph_context_skips_non_python():
    """非 Python 文件应被跳过"""
    diff_content = "+function target() { helper(); }\n"
    parsed = ParsedDiff(
        files=[_make_file("src/mod.js", diff_content)],
        total_additions=1,
        total_deletions=0,
    )

    def fake_get(url, path, ref):
        return "function target() {}"

    ctx = build_impact_graph_context(parsed, fake_get, "repo", "ref")
    assert ctx == ""


def test_build_impact_graph_context_skips_binary():
    from ai_pr_review.models import FileDiff
    binary_file = FileDiff(
        path="img.png",
        change_type=ChangeType.ADDED,
        hunks=[],
        additions=0,
        deletions=0,
        is_binary=True,
    )
    parsed = ParsedDiff(files=[binary_file], total_additions=0, total_deletions=0)

    ctx = build_impact_graph_context(parsed, lambda *a: "", "repo", "ref")
    assert ctx == ""


def test_build_impact_graph_context_empty_when_no_changed_functions():
    """diff 中没有新增 def 时，应返回空字符串"""
    diff_content = "+x = 1\n"
    parsed = ParsedDiff(
        files=[_make_file("mod.py", diff_content)],
        total_additions=1,
        total_deletions=0,
    )

    ctx = build_impact_graph_context(parsed, lambda *a: "def x(): pass", "repo", "ref")
    assert ctx == ""


def test_build_impact_graph_context_handles_fetch_failure():
    """文件拉取异常时应跳过，不抛错"""
    diff_content = "+def target():\n+    pass\n"
    parsed = ParsedDiff(
        files=[_make_file("mod.py", diff_content)],
        total_additions=2,
        total_deletions=0,
    )

    def fake_get(url, path, ref):
        raise RuntimeError("network error")

    ctx = build_impact_graph_context(parsed, fake_get, "repo", "ref")
    assert ctx == ""
