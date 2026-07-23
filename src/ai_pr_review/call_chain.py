"""AST 级函数调用链分析 — 识别变更函数的调用方和被调用方"""
import ast
import re
import logging
from ai_pr_review.models import ParsedDiff, FileDiff, DiffHunk, ChangeType

logger = logging.getLogger(__name__)

# 从 diff hunk 中提取新增行中定义的函数名
FUNC_DEF_PATTERN = re.compile(r"^\+\s*(?:async\s+)?def\s+(\w+)\s*\(", re.MULTILINE)
# 从 diff hunk 中提取新增行中调用的函数名
FUNC_CALL_PATTERN = re.compile(r"^\+\s*(\w+)\s*\(", re.MULTILINE)


def extract_changed_functions(file_diff: FileDiff) -> list[str]:
    """从 diff hunk 中提取新增/修改的函数名"""
    functions = set()
    for hunk in file_diff.hunks:
        for match in FUNC_DEF_PATTERN.finditer(hunk.content):
            functions.add(match.group(1))
    return list(functions)


def extract_called_functions(file_diff: FileDiff) -> list[str]:
    """从 diff hunk 中提取新增行中调用的函数名"""
    calls = set()
    for hunk in file_diff.hunks:
        for match in FUNC_CALL_PATTERN.finditer(hunk.content):
            func_name = match.group(1)
            # 过滤掉关键字和常见内置函数
            if func_name not in {"if", "for", "while", "print", "len", "range", "str", "int", "float", "dict", "list", "set", "tuple", "bool", "isinstance", "hasattr", "getattr", "setattr", "super", "type"}:
                calls.add(func_name)
    return list(calls)


def analyze_call_chain(file_content: str, target_functions: list[str]) -> dict:
    """分析文件内容，找出目标函数的调用方和被调用方

    返回: {
        "callers": {"func_name": ["caller1", "caller2"]},
        "callees": {"func_name": ["callee1", "callee2"]},
    }
    """
    callers = {f: [] for f in target_functions}
    callees = {f: [] for f in target_functions}

    try:
        tree = ast.parse(file_content)
    except SyntaxError:
        return {"callers": callers, "callees": callees}

    # 遍历 AST，找出谁调用了目标函数，目标函数调用了谁
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
            func_name = node.name
            # 如果这是目标函数，找出它调用了谁
            if func_name in target_functions:
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        called_name = _get_call_name(child)
                        if called_name and called_name not in callees[func_name]:
                            callees[func_name].append(called_name)
            # 检查这个函数是否调用了目标函数
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    called_name = _get_call_name(child)
                    if called_name in target_functions and func_name not in callers[called_name]:
                        callers[called_name].append(func_name)

    return {"callers": callers, "callees": callees}


def _get_call_name(call_node: ast.Call) -> str:
    """从 Call 节点提取被调用函数名"""
    if isinstance(call_node.func, ast.Name):
        return call_node.func.id
    elif isinstance(call_node.func, ast.Attribute):
        return call_node.func.attr
    return ""


def build_call_chain_context(
    parsed_diff: ParsedDiff,
    get_file_content_fn,
    repo_url: str,
    ref: str,
) -> str:
    """构建调用链上下文文本"""
    parts = []

    for file_diff in parsed_diff.files:
        if file_diff.is_binary or file_diff.is_generated:
            continue
        if not file_diff.path.endswith(".py"):
            continue

        changed_funcs = extract_changed_functions(file_diff)
        if not changed_funcs:
            continue

        # 拉取完整文件内容做 AST 分析
        try:
            content = get_file_content_fn(repo_url, file_diff.path, ref)
            if not content:
                continue
        except Exception:
            continue

        chain = analyze_call_chain(content, changed_funcs)

        # 构建上下文文本
        for func_name in changed_funcs:
            callers = chain["callers"].get(func_name, [])
            callees = chain["callees"].get(func_name, [])

            if callers or callees:
                info_parts = [f"### {file_diff.path}::{func_name}()"]
                if callers:
                    info_parts.append(f"  调用方: {', '.join(callers[:5])}")
                if callees:
                    info_parts.append(f"  被调用: {', '.join(callees[:10])}")
                parts.append("\n".join(info_parts))

    if parts:
        header = "## 函数调用链分析（变更函数的调用关系）\n"
        return header + "\n".join(parts)
    return ""
