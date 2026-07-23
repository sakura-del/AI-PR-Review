"""跨文件依赖上下文构建器"""
import re
import logging
from ai_pr_review.models import ParsedDiff

logger = logging.getLogger(__name__)

# 匹配各种语言的 import 语句
IMPORT_PATTERNS = {
    # Python: from X import Y / import X
    "python": [
        re.compile(r"^\s*from\s+([\w.]+)\s+import", re.MULTILINE),
        re.compile(r"^\s*import\s+([\w.]+)", re.MULTILINE),
    ],
    # JavaScript/TypeScript: import X from 'Y' / require('Y')
    "javascript": [
        re.compile(r"^\s*import\s+.*\s+from\s+['\"]([^'\"]+)['\"]", re.MULTILINE),
        re.compile(r"^\s*import\s+['\"]([^'\"]+)['\"]", re.MULTILINE),
        re.compile(r"require\(\s*['\"]([^'\"]+)['\"]\s*\)", re.MULTILINE),
    ],
    # Go: import "X" / import X "Y"
    "go": [
        re.compile(r'^\s*import\s+"([^"]+)"', re.MULTILINE),
        re.compile(r'import\s+\w+\s+"([^"]+)"', re.MULTILINE),
    ],
    # Java: import X.Y.Z;
    "java": [
        re.compile(r"^\s*import\s+([\w.]+);", re.MULTILINE),
    ],
}


def _detect_language(file_path: str) -> str:
    """根据文件扩展名检测语言"""
    ext_map = {
        ".py": "python",
        ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
        ".ts": "javascript", ".tsx": "javascript",
        ".go": "go",
        ".java": "java",
    }
    for ext, lang in ext_map.items():
        if file_path.endswith(ext):
            return lang
    return ""


def _resolve_import_path(import_path: str, current_file: str, language: str) -> str:
    """将 import 路径解析为仓库内文件路径"""
    if language == "python":
        # from a.b.c import X → a/b/c.py or a/b/c/__init__.py
        parts = import_path.replace(".", "/")
        candidates = [f"{parts}.py", f"{parts}/__init__.py"]
        return candidates[0]  # 返回第一个候选，调用方负责验证
    elif language in ("javascript", "typescript"):
        # 相对路径解析
        if import_path.startswith("."):
            current_dir = "/".join(current_file.split("/")[:-1])
            base = f"{current_dir}/{import_path.lstrip('./')}"
            candidates = [f"{base}.js", f"{base}.jsx", f"{base}.ts", f"{base}.tsx", f"{base}/index.js", f"{base}/index.ts"]
            return candidates[0]
        return ""
    elif language == "go":
        # Go import 通常是完整路径，无法直接映射到文件
        return ""
    elif language == "java":
        # import a.b.c → a/b/c.java
        return import_path.replace(".", "/") + ".java"
    return ""


def extract_dependencies(parsed_diff: ParsedDiff) -> dict[str, list[str]]:
    """从 diff 中提取所有文件的依赖关系

    返回: {变更文件路径: [被依赖的文件路径列表]}
    """
    dependencies = {}
    for file_diff in parsed_diff.files:
        if file_diff.is_binary or file_diff.is_generated:
            continue
        language = _detect_language(file_diff.path)
        if not language:
            continue
        patterns = IMPORT_PATTERNS.get(language, [])
        # 合并所有 hunk 内容
        content = "\n".join(h.content for h in file_diff.hunks)
        imports = set()
        for pattern in patterns:
            for match in pattern.finditer(content):
                import_path = match.group(1)
                resolved = _resolve_import_path(import_path, file_diff.path, language)
                if resolved:
                    imports.add(resolved)
        if imports:
            dependencies[file_diff.path] = list(imports)
    return dependencies


def build_cross_file_context(
    parsed_diff: ParsedDiff,
    get_file_content_fn,
    repo_url: str,
    ref: str,
    max_files: int = 5,
    max_content_length: int = 3000,
) -> str:
    """构建跨文件依赖上下文

    提取变更文件的依赖，拉取被引用文件内容，组装为上下文文本。
    """
    deps = extract_dependencies(parsed_diff)
    if not deps:
        return ""

    # 收集所有需要拉取的依赖文件（去重，排除已变更的文件本身）
    changed_files = {f.path for f in parsed_diff.files}
    all_deps = set()
    for dep_list in deps.values():
        for dep in dep_list:
            if dep not in changed_files:
                all_deps.add(dep)

    # 限制数量
    deps_to_fetch = list(all_deps)[:max_files]

    parts = []
    for dep_path in deps_to_fetch:
        try:
            content = get_file_content_fn(repo_url, dep_path, ref)
            if content:
                # 截断过长内容
                if len(content) > max_content_length:
                    content = content[:max_content_length] + "\n... (truncated)"
                parts.append(f"[依赖文件: {dep_path}]\n{content}")
        except Exception as e:
            logger.debug(f"Failed to fetch dependency {dep_path}: {e}")

    if parts:
        header = "## 跨文件依赖上下文（变更文件引用的其他文件）\n"
        return header + "\n\n".join(parts)
    return ""
