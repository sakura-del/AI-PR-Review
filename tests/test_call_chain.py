"""call_chain 模块测试"""
from ai_pr_review.call_chain import (
    extract_changed_functions,
    extract_called_functions,
    analyze_call_chain,
    build_call_chain_context,
)
from ai_pr_review.models import (
    ParsedDiff,
    FileDiff,
    DiffHunk,
    ChangeType,
)


def _make_hunk(file_path: str, content: str) -> DiffHunk:
    """构造测试用 DiffHunk"""
    return DiffHunk(
        file_path=file_path,
        change_type=ChangeType.MODIFIED,
        old_start=1,
        old_count=1,
        new_start=1,
        new_count=1,
        content=content,
        header="@@ -1,1 +1,1 @@",
    )


def _make_file(path: str, content: str, change_type: ChangeType = ChangeType.MODIFIED) -> FileDiff:
    """构造测试用 FileDiff"""
    return FileDiff(
        path=path,
        change_type=change_type,
        hunks=[_make_hunk(path, content)],
        additions=1,
        deletions=1,
    )


def _make_diff(files: list[FileDiff]) -> ParsedDiff:
    """构造测试用 ParsedDiff"""
    return ParsedDiff(
        files=files,
        total_additions=sum(f.additions for f in files),
        total_deletions=sum(f.deletions for f in files),
    )


def test_extract_changed_functions():
    """应从 diff hunk 中提取新增的函数名（含同步与 async）"""
    content = "+def foo():\n+    pass\n+\n+async def bar():\n+    pass\n-old():\n    pass\n"
    file_diff = _make_file("src/main.py", content)
    funcs = extract_changed_functions(file_diff)
    # foo 与 bar 应被提取，old 行（以 - 开头）不应被提取
    assert "foo" in funcs
    assert "bar" in funcs
    assert "old" not in funcs


def test_extract_called_functions():
    """应从 diff hunk 中提取新增行中调用的函数名，并过滤关键字和常见内置函数"""
    content = "+foo()\n+bar()\n+print(x)\n+len(y)\n+if(cond):\n+    pass\n"
    file_diff = _make_file("src/main.py", content)
    calls = extract_called_functions(file_diff)
    # foo 与 bar 应被提取
    assert "foo" in calls
    assert "bar" in calls
    # print、len 与 if 应被过滤
    assert "print" not in calls
    assert "len" not in calls
    assert "if" not in calls


def test_analyze_call_chain_callers():
    """应找出调用了目标函数的所有调用方"""
    content = (
        "def foo():\n"
        "    pass\n"
        "\n"
        "def bar():\n"
        "    foo()\n"
        "\n"
        "def baz():\n"
        "    foo()\n"
    )
    result = analyze_call_chain(content, ["foo"])
    # bar 与 baz 都调用了 foo
    assert "bar" in result["callers"]["foo"]
    assert "baz" in result["callers"]["foo"]
    # foo 不应作为自己的调用方
    assert "foo" not in result["callers"]["foo"]


def test_analyze_call_chain_callees():
    """应找出目标函数调用的所有被调用方"""
    content = (
        "def helper():\n"
        "    pass\n"
        "\n"
        "def other():\n"
        "    pass\n"
        "\n"
        "def foo():\n"
        "    helper()\n"
        "    other()\n"
    )
    result = analyze_call_chain(content, ["foo"])
    # foo 调用了 helper 与 other
    assert "helper" in result["callees"]["foo"]
    assert "other" in result["callees"]["foo"]


def test_analyze_call_chain_syntax_error():
    """语法错误时应返回空的调用方与被调用方列表"""
    content = "def foo(\n    pass\n"  # 缺少右括号，语法错误
    result = analyze_call_chain(content, ["foo"])
    assert result["callers"] == {"foo": []}
    assert result["callees"] == {"foo": []}


def test_build_call_chain_context():
    """应拉取文件内容并构建调用链上下文文本"""
    diff_content = "+def foo():\n+    helper()\n"
    file_diff = _make_file("src/main.py", diff_content)
    parsed = _make_diff([file_diff])

    # 模拟完整文件内容：foo 调用了 helper，bar 调用了 foo
    file_content = (
        "def helper():\n"
        "    pass\n"
        "\n"
        "def foo():\n"
        "    helper()\n"
        "\n"
        "def bar():\n"
        "    foo()\n"
    )

    def fake_get(repo_url: str, file_path: str, ref: str) -> str:
        if file_path == "src/main.py":
            return file_content
        return ""

    result = build_call_chain_context(parsed, fake_get, "", "")
    assert "函数调用链分析" in result
    assert "src/main.py::foo()" in result
    # foo 调用了 helper，应出现在被调用列表
    assert "被调用" in result
    assert "helper" in result
    # bar 调用了 foo，应出现在调用方列表
    assert "调用方" in result
    assert "bar" in result


def test_build_call_chain_context_no_python():
    """非 Python 文件应被跳过，返回空字符串"""
    diff_content = "+function foo() {\n+    bar();\n+}\n"
    file_diff = _make_file("src/main.js", diff_content)
    parsed = _make_diff([file_diff])

    result = build_call_chain_context(parsed, lambda *a: "", "", "")
    assert result == ""


def test_build_call_chain_context_no_functions():
    """无函数定义变更时应返回空字符串"""
    diff_content = "+x = 1\n+y = 2\n+z = x + y\n"
    file_diff = _make_file("src/main.py", diff_content)
    parsed = _make_diff([file_diff])

    result = build_call_chain_context(parsed, lambda *a: "", "", "")
    assert result == ""


def test_analyze_call_chain_attribute_call():
    """应能识别属性调用（如 self.method() 或 obj.method()）"""
    content = (
        "class Service:\n"
        "    def run(self):\n"
        "        self.process()\n"
        "        helper()\n"
        "\n"
        "def helper():\n"
        "    pass\n"
    )
    # run 是目标函数，应识别 self.process 的属性名为 process
    result = analyze_call_chain(content, ["run"])
    assert "process" in result["callees"]["run"]
    assert "helper" in result["callees"]["run"]


def test_build_call_chain_context_binary_file():
    """二进制文件应被跳过，返回空字符串"""
    diff_content = "+def foo():\n+    pass\n"
    file_diff = _make_file("src/main.py", diff_content)
    file_diff.is_binary = True
    parsed = _make_diff([file_diff])

    result = build_call_chain_context(parsed, lambda *a: "CONTENT", "", "")
    assert result == ""
