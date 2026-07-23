"""dependency_extractor 模块测试"""
from ai_pr_review.dependency_extractor import (
    _detect_language,
    _resolve_import_path,
    extract_dependencies,
    build_cross_file_context,
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


def test_extract_python_imports():
    """Python 文件应能提取 from...import 与 import 语句"""
    content = "from foo.bar import baz\nimport os\nimport ai_pr_review.models"
    parsed = _make_diff([_make_file("src/main.py", content)])
    deps = extract_dependencies(parsed)
    assert "src/main.py" in deps
    # foo.bar → foo/bar.py，os → os.py，ai_pr_review.models → ai_pr_review/models.py
    assert "foo/bar.py" in deps["src/main.py"]
    assert "os.py" in deps["src/main.py"]
    assert "ai_pr_review/models.py" in deps["src/main.py"]


def test_extract_javascript_imports():
    """JS 文件应能提取 import...from、裸 import 与 require"""
    content = "import { x } from './utils'\nimport './styles'\nrequire('./config')"
    parsed = _make_diff([_make_file("src/index.js", content)])
    deps = extract_dependencies(parsed)
    assert "src/index.js" in deps
    dep_list = deps["src/index.js"]
    # 相对路径解析：./utils → src/utils.js，./styles → src/styles.js，./config → src/config.js
    assert "src/utils.js" in dep_list
    assert "src/styles.js" in dep_list
    assert "src/config.js" in dep_list


def test_extract_go_imports():
    """Go 文件 import 路径无法映射到仓库内文件，依赖应为空"""
    content = 'import "fmt"\nimport utils "github.com/foo/utils"'
    parsed = _make_diff([_make_file("main.go", content)])
    deps = extract_dependencies(parsed)
    # Go 的 import 解析返回空字符串，故不产生依赖
    assert deps == {}


def test_extract_java_imports():
    """Java 文件应能提取 import 语句并映射为 .java 路径"""
    content = "import com.example.Utils;\nimport java.util.List;"
    parsed = _make_diff([_make_file("Main.java", content)])
    deps = extract_dependencies(parsed)
    assert "Main.java" in deps
    assert "com/example/Utils.java" in deps["Main.java"]
    assert "java/util/List.java" in deps["Main.java"]


def test_detect_language():
    """根据扩展名应正确识别语言"""
    assert _detect_language("foo.py") == "python"
    assert _detect_language("foo.js") == "javascript"
    assert _detect_language("foo.jsx") == "javascript"
    assert _detect_language("foo.mjs") == "javascript"
    assert _detect_language("foo.ts") == "javascript"
    assert _detect_language("foo.tsx") == "javascript"
    assert _detect_language("foo.go") == "go"
    assert _detect_language("foo.java") == "java"
    # 未知扩展名返回空字符串
    assert _detect_language("foo.txt") == ""
    assert _detect_language("foo.md") == ""


def test_resolve_import_path_python():
    """Python import 路径应将点号转为斜杠并追加 .py 后缀"""
    assert _resolve_import_path("foo.bar", "src/main.py", "python") == "foo/bar.py"
    assert _resolve_import_path("os", "main.py", "python") == "os.py"


def test_resolve_import_path_javascript_relative():
    """JS 相对路径应基于当前文件目录解析"""
    # ./utils 在 src/index.js 中引用 → src/utils.js
    assert _resolve_import_path("./utils", "src/index.js", "javascript") == "src/utils.js"
    # 非相对路径（如 npm 包名）应返回空字符串
    assert _resolve_import_path("react", "src/index.js", "javascript") == ""


def test_build_cross_file_context():
    """应拉取被引用文件内容并组装为上下文文本"""
    content = "from foo.bar import baz"
    parsed = _make_diff([_make_file("src/main.py", content)])

    def fake_get(repo_url: str, file_path: str, ref: str) -> str:
        if file_path == "foo/bar.py":
            return "FOO_BAR_CONTENT"
        return ""

    result = build_cross_file_context(parsed, fake_get, "", "")
    assert "## 跨文件依赖上下文" in result
    assert "[依赖文件: foo/bar.py]" in result
    assert "FOO_BAR_CONTENT" in result


def test_build_cross_file_context_no_deps():
    """无依赖时应返回空字符串"""
    # .txt 文件不识别语言，无法提取依赖
    parsed = _make_diff([_make_file("README.txt", "hello")])
    result = build_cross_file_context(parsed, lambda *a: "", "", "")
    assert result == ""


def test_build_cross_file_context_fetch_error():
    """拉取依赖文件抛异常时应被吞掉并返回空字符串"""
    content = "from foo.bar import baz"
    parsed = _make_diff([_make_file("src/main.py", content)])

    def raising_get(repo_url: str, file_path: str, ref: str) -> str:
        raise RuntimeError("network error")

    result = build_cross_file_context(parsed, raising_get, "", "")
    assert result == ""


def test_build_cross_file_context_excludes_changed_files():
    """已变更文件本身不应作为依赖再次拉取"""
    # main.py 引用 helper，但 helper 也在变更列表中
    files = [
        _make_file("src/main.py", "from src.helper import do"),
        _make_file("src/helper.py", "def do(): pass"),
    ]
    parsed = _make_diff(files)

    fetched = []

    def fake_get(repo_url: str, file_path: str, ref: str) -> str:
        fetched.append(file_path)
        return "CONTENT"

    result = build_cross_file_context(parsed, fake_get, "", "")
    # src/helper.py 已在变更列表中，不应被再次拉取
    assert "src/helper.py" not in fetched
    assert result == ""


def test_build_cross_file_context_truncates_long_content():
    """过长的依赖文件内容应被截断"""
    long_content = "x" * 5000
    parsed = _make_diff([_make_file("src/main.py", "from foo.bar import baz")])

    def fake_get(repo_url: str, file_path: str, ref: str) -> str:
        return long_content

    result = build_cross_file_context(
        parsed, fake_get, "", "", max_files=3, max_content_length=100
    )
    assert "... (truncated)" in result
    # 截断后内容不应包含完整的 5000 字符
    assert len(result) < len(long_content)
