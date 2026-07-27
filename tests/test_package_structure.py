"""包结构约束测试（T10 [A6]）

防止架构腐烂：固化 v0.9 包结构，任何违反依赖方向的 import 都会失败。

分层规则：
- core/ 可依赖 data/、platforms/、infra（共用 utilities）
- data/ 不可依赖 core/、cli/、server/、platforms/
- platforms/ 不可依赖 core/、cli/、server/、data/
- server/ 可依赖 core/、data/、platforms/（用于 API 实现）
- cli/ 是顶层入口，可依赖一切

简化的硬约束（CI 卡死）：
- cli/ 不能被 core/、data/、platforms/、server/ 反向依赖
- server/ 不能被 core/、data/ 反向依赖（避免循环）
- platforms/ 保持纯 I/O 客户端，不带业务逻辑
"""
import ast
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "ai_pr_review"


def _get_module_path(file_path: Path) -> str:
    """把文件路径转成模块名（点分形式）"""
    rel = file_path.relative_to(SRC_ROOT)
    parts = list(rel.parts)
    if parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(["ai_pr_review"] + parts) if parts else "ai_pr_review"


def _get_imports(file_path: Path) -> list[str]:
    """提取文件中的所有 ai_pr_review.* 引用"""
    content = file_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    imports = []

    class Visitor(ast.NodeVisitor):
        def visit_ImportFrom(self, node: ast.ImportFrom):
            if node.module and node.module.startswith("ai_pr_review"):
                imports.append(node.module)
                # 也处理 `from ai_pr_review.X import Y` 中的子模块
                for alias in node.names:
                    if alias.name.startswith("ai_pr_review"):
                        imports.append(alias.name)
            self.generic_visit(node)

        def visit_Import(self, node: ast.Import):
            for alias in node.names:
                if alias.name.startswith("ai_pr_review"):
                    imports.append(alias.name)
            self.generic_visit(node)

    Visitor().visit(tree)
    return imports


def _collect_violations(subpackage: str, forbidden_prefixes: list[str]) -> list[tuple[Path, str, str]]:
    """收集 subpackage 目录中违反 forbidden_prefixes 规则的 import

    Returns: [(file_path, source_module, forbidden_import), ...]
    """
    sub_path = SRC_ROOT / subpackage
    if not sub_path.exists():
        return []

    violations = []
    for py_file in sub_path.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        if py_file.name == "__init__.py":
            continue
        source_module = _get_module_path(py_file)
        for imp in _get_imports(py_file):
            for forbidden in forbidden_prefixes:
                if imp == forbidden or imp.startswith(forbidden + "."):
                    violations.append((py_file, source_module, imp))
    return violations


# ===== 反向依赖约束（架构红线）=====

def test_cli_cannot_be_imported_by_other_layers():
    """cli/ 是顶层入口，其他层不应依赖它"""
    forbidden_prefixes = ["ai_pr_review.cli"]
    for subpackage in ["core", "data", "platforms", "server"]:
        violations = _collect_violations(subpackage, forbidden_prefixes)
        assert not violations, (
            f"{subpackage}/ 反向依赖 cli/：\n"
            + "\n".join(f"  {m}: imports {i}" for _, m, i in violations)
        )


def test_server_cannot_be_imported_by_lower_layers():
    """server/ 不应被 core/、data/ 反向依赖（避免循环）"""
    forbidden_prefixes = ["ai_pr_review.server"]
    for subpackage in ["core", "data"]:
        violations = _collect_violations(subpackage, forbidden_prefixes)
        assert not violations, (
            f"{subpackage}/ 反向依赖 server/：\n"
            + "\n".join(f"  {m}: imports {i}" for _, m, i in violations)
        )


def test_platforms_cannot_be_imported_by_lower_layers():
    """platforms/ 是 I/O 客户端层（叶子节点），反向依赖受严格控制

    规则：
    - platforms/ 不能依赖 data/、server/、cli/（保持纯 I/O 客户端）
    - platforms/ 可以依赖 core.models（数据类）+ core.retry（HTTP 工具）
    - platforms/ 不应依赖 core.analyzer / core.config / core.expert_knowledge 等业务模块
    - core/ 可以依赖 platforms/（业务需要 I/O）
    - data/、cli/ 不应直接依赖 platforms/（用 core/ 的封装）

    本测试检查"platforms/ 不能反向依赖其他业务层"。
    """
    # 允许 core.models + core.retry（叶子工具），禁止其他业务模块
    allowed_in_core = {"ai_pr_review.core.models", "ai_pr_review.core.retry"}
    forbidden_prefixes = [
        "ai_pr_review.data",
        "ai_pr_review.server",
        "ai_pr_review.cli",
    ]

    sub_path = SRC_ROOT / "platforms"
    if not sub_path.exists():
        return

    violations = []
    for py_file in sub_path.rglob("*.py"):
        if "__pycache__" in str(py_file) or py_file.name == "__init__.py":
            continue
        source_module = _get_module_path(py_file)
        for imp in _get_imports(py_file):
            if imp in allowed_in_core:
                continue
            if imp.startswith("ai_pr_review.core"):
                violations.append((py_file, source_module, imp))
                continue
            for forbidden in forbidden_prefixes:
                if imp == forbidden or imp.startswith(forbidden + "."):
                    violations.append((py_file, source_module, imp))

    assert not violations, (
        "platforms/ 反向依赖业务层（应保持纯 I/O 客户端）：\n"
        + "\n".join(f"  {m}: imports {i}" for _, m, i in violations)
    )


# ===== 子包存在性约束 =====

@pytest.mark.parametrize("subpackage", ["core", "data", "platforms", "server", "cli"])
def test_subpackage_has_init(subpackage):
    """每个子包必须有 __init__.py（即使是空的）"""
    init_file = SRC_ROOT / subpackage / "__init__.py"
    assert init_file.exists(), f"{subpackage}/ 缺少 __init__.py"


@pytest.mark.parametrize("subpackage,expected_modules", [
    ("core", ["models.py", "analyzer.py", "config.py", "expert_knowledge.py"]),
    ("data", ["storage.py", "job_queue.py", "history.py", "cache.py", "team_rules.py"]),
    ("platforms", ["github_client.py", "platform.py"]),
    ("server", ["api_server.py", "webhook.py", "dashboard.py"]),
    ("cli", ["cli.py"]),
])
def test_subpackage_contains_expected_modules(subpackage, expected_modules):
    """每个子包应包含预期的核心模块（防止遗漏）"""
    sub_path = SRC_ROOT / subpackage
    for module_name in expected_modules:
        module_path = sub_path / module_name
        assert module_path.exists(), f"{subpackage}/{module_name} 缺失"


# ===== Persistence 子包独立 =====

def test_persistence_subpackage_is_separate_from_data():
    """persistence/ 独立子包，便于 Storage 实现可替换"""
    persistence_path = SRC_ROOT / "data" / "persistence"
    assert persistence_path.exists()
    assert (persistence_path / "__init__.py").exists()
    assert (persistence_path / "local_json.py").exists()
    assert (persistence_path / "sqlite.py").exists()
    assert (persistence_path / "factory.py").exists()


# ===== 没有意外残留的扁平结构 =====

def test_no_python_files_at_package_root():
    """ai_pr_review/ 根目录不应再有 .py 文件（除 __init__.py）

    所有业务模块应在子包内。
    """
    for item in SRC_ROOT.iterdir():
        if item.is_file() and item.suffix == ".py":
            assert item.name == "__init__.py", (
                f"根目录有遗留 .py 文件：{item.name}（应移到子包）"
            )


def test_no_python_files_in_data_persistence_subdirs_should_exist_only_there():
    """persistence/ 下的 Storage 实现不重复在其他地方"""
    # 检查所有 .py 文件，确保没有两个文件实现 Storage
    storage_modules = list(SRC_ROOT.rglob("storage.py"))
    storage_modules.extend(SRC_ROOT.rglob("local_json*.py"))
    storage_modules.extend(SRC_ROOT.rglob("sqlite*.py"))
    assert len(storage_modules) >= 3, (
        f"Storage 实现不完整，应至少 3 个：{storage_modules}"
    )