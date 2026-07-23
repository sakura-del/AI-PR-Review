"""增量影响图 — 基于现有 AST 模块构建受变更函数影响的闭包子图

设计目标：
- 仅检索受变更影响的最小子图，避免拉取整个代码库
- 复用 call_chain.py 的 AST 分析能力，零额外依赖
- callers / callees 各限制深度 2 层，避免上下文膨胀
"""
import ast
import logging
from ai_pr_review.models import ParsedDiff
from ai_pr_review.call_chain import extract_changed_functions, _get_call_name

logger = logging.getLogger(__name__)

# 闭包遍历最大深度（callers 与 callees 各 max_depth 层）
DEFAULT_MAX_DEPTH = 2
# 每层节点数上限，防止爆炸式扩散
DEFAULT_MAX_NODES_PER_LEVEL = 8


def _collect_all_calls(file_content: str) -> dict[str, list[str]]:
    """解析文件，返回 {函数名: [它调用的函数名列表]}

    用于构建 callees 闭包：从变更函数出发，递归找出它调用了谁、又调用了谁。
    """
    call_map: dict[str, list[str]] = {}
    try:
        tree = ast.parse(file_content)
    except SyntaxError:
        return call_map

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            callees = []
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    name = _get_call_name(child)
                    if name and name not in callees:
                        callees.append(name)
            call_map[node.name] = callees
    return call_map


def _collect_all_callers(file_content: str) -> dict[str, list[str]]:
    """解析文件，返回 {被调用函数名: [调用它的函数名列表]}

    用于构建 callers 闭包：从变更函数出发，递归找出谁调用了它、谁又调用了那个调用者。
    """
    caller_map: dict[str, list[str]] = {}
    try:
        tree = ast.parse(file_content)
    except SyntaxError:
        return caller_map

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            caller_func = node.name
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    called = _get_call_name(child)
                    if called:
                        caller_map.setdefault(called, [])
                        if caller_func not in caller_map[called]:
                            caller_map[called].append(caller_func)
    return caller_map


def _bfs_closure(
    start_nodes: list[str],
    edge_map: dict[str, list[str]],
    max_depth: int,
    max_per_level: int,
) -> dict[str, list[str]]:
    """广度优先遍历构建闭包，限制深度与每层节点数

    返回 {起点函数: [按深度展开的可达函数列表（不含起点本身）]}
    """
    result: dict[str, list[str]] = {}
    for start in start_nodes:
        visited = {start}
        ordered: list[str] = []
        frontier = [start]
        for _ in range(max_depth):
            next_frontier: list[str] = []
            for node in frontier:
                # 防御性：节点不在 edge_map 中时跳过
                for neighbor in edge_map.get(node, [])[:max_per_level]:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        ordered.append(neighbor)
                        next_frontier.append(neighbor)
            frontier = next_frontier
            if not frontier:
                break
        result[start] = ordered
    return result


def build_impact_subgraph(
    file_content: str,
    changed_functions: list[str],
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_per_level: int = DEFAULT_MAX_NODES_PER_LEVEL,
) -> dict:
    """对单文件构建变更函数的影响子图

    返回: {
        "callers": {func: [向上展开的调用方...]},
        "callees": {func: [向下展开的被调用方...]},
    }
    """
    if not changed_functions:
        return {"callers": {}, "callees": {}}

    callee_map = _collect_all_calls(file_content)
    caller_map = _collect_all_callers(file_content)

    callers_closure = _bfs_closure(changed_functions, caller_map, max_depth, max_per_level)
    callees_closure = _bfs_closure(changed_functions, callee_map, max_depth, max_per_level)

    return {"callers": callers_closure, "callees": callees_closure}


def build_impact_graph_context(
    parsed_diff: ParsedDiff,
    get_file_content_fn,
    repo_url: str,
    ref: str,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_per_level: int = DEFAULT_MAX_NODES_PER_LEVEL,
) -> str:
    """构建增量影响图上下文文本

    遍历变更文件，提取变更函数，构建 callers/callees 闭包，
    仅输出受影响的最小函数集合，避免注入冗余上下文。
    """
    parts: list[str] = []

    for file_diff in parsed_diff.files:
        if file_diff.is_binary or file_diff.is_generated:
            continue
        if not file_diff.path.endswith(".py"):
            continue

        changed_funcs = extract_changed_functions(file_diff)
        if not changed_funcs:
            continue

        try:
            content = get_file_content_fn(repo_url, file_diff.path, ref)
            if not content:
                continue
        except Exception:
            continue

        subgraph = build_impact_subgraph(content, changed_funcs, max_depth, max_per_level)

        # 仅当存在非空闭包时输出，避免无信息条目
        has_info = any(subgraph["callers"].get(f) or subgraph["callees"].get(f) for f in changed_funcs)
        if not has_info:
            continue

        parts.append(f"### {file_diff.path}")
        for func in changed_funcs:
            callers = subgraph["callers"].get(func, [])
            callees = subgraph["callees"].get(func, [])
            line = f"- `{func}()`"
            if callers:
                line += f" | 调用方链: {' → '.join(callers[:6])}"
            if callees:
                line += f" | 被调用链: {' → '.join(callees[:6])}"
            parts.append(line)

    if parts:
        header = "## 增量影响图（受变更函数影响的最小调用子图，深度限制 %d 层）\n" % max_depth
        return header + "\n".join(parts)
    return ""
