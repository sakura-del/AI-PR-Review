"""轻量级 RAG 知识库 — 基于 TF-IDF 检索历史审查经验

设计目标：
- 复用 ~/.ai-pr-review/cache/ 中已积累的分析结果作为知识源
- 纯标准库实现 TF-IDF + 余弦相似度，避免引入 numpy / sklearn 重依赖
- 检索 top-K 相似 PR 经验注入当前 AI 上下文，提升审查一致性
"""
import json
import math
import re
import logging
from pathlib import Path
from ai_pr_review.models import ParsedDiff, PRMetadata

logger = logging.getLogger(__name__)

# 知识库源目录：复用缓存目录中已保存的完整分析结果
KB_DIR = Path.home() / ".ai-pr-review" / "cache"
# 默认检索 top-K
DEFAULT_TOP_K = 3
# 最小相似度阈值，避免注入弱相关条目
DEFAULT_MIN_SIMILARITY = 0.05

# 中文/英文混合分词：英文按非单词字符切分，中文按字符切分
_TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[\u4e00-\u9fa5]")


def _tokenize(text: str) -> list[str]:
    """混合分词：英文按标识符，中文按单字

    选择这种简单分词避免 jieba 重依赖，对审查场景（多为代码标识符）已足够。
    """
    if not text:
        return []
    return _TOKEN_PATTERN.findall(text.lower())


def _build_tfidf_vectors(
    documents: list[list[str]],
) -> tuple[list[dict[str, float]], dict[str, float]]:
    """构建 TF-IDF 向量

    返回 (每篇文档的 tfidf 向量列表, 全局 idf 字典)
    """
    if not documents:
        return [], {}

    # 统计文档频率
    doc_count = len(documents)
    df: dict[str, int] = {}
    for tokens in documents:
        for token in set(tokens):
            df[token] = df.get(token, 0) + 1

    # IDF：加 1 平滑防止除零
    idf = {token: math.log((doc_count + 1) / (cnt + 1)) + 1.0 for token, cnt in df.items()}

    # 每篇文档的 TF-IDF 向量（L2 归一化以便余弦相似度简化为点积）
    vectors: list[dict[str, float]] = []
    for tokens in documents:
        tf: dict[str, int] = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1
        token_count = len(tokens) or 1
        vec: dict[str, float] = {}
        for t, cnt in tf.items():
            vec[t] = (cnt / token_count) * idf.get(t, 0.0)
        # L2 归一化
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        vec = {t: v / norm for t, v in vec.items()}
        vectors.append(vec)
    return vectors, idf


def _to_tfidf_vector(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    """将查询文本转为与文档向量同空间的 TF-IDF 向量"""
    if not tokens:
        return {}
    tf: dict[str, int] = {}
    for t in tokens:
        tf[t] = tf.get(t, 0) + 1
    token_count = len(tokens)
    vec: dict[str, float] = {}
    for t, cnt in tf.items():
        vec[t] = (cnt / token_count) * idf.get(t, 0.0)
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {t: v / norm for t, v in vec.items()}


def _cosine_similarity(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    """已归一化向量的余弦相似度 = 点积"""
    if not vec_a or not vec_b:
        return 0.0
    # 在较短向量上迭代以减少比较次数
    if len(vec_a) > len(vec_b):
        vec_a, vec_b = vec_b, vec_a
    return sum(weight * vec_b.get(token, 0.0) for token, weight in vec_a.items())


def _load_knowledge_base() -> list[dict]:
    """从缓存目录加载历史审查记录作为知识库源"""
    if not KB_DIR.exists():
        return []
    records: list[dict] = []
    for f in KB_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            # 仅保留包含必要字段的记录，避免损坏数据污染检索
            if data.get("summary") and (data.get("findings") or data.get("suggestions")):
                records.append(data)
        except (json.JSONDecodeError, OSError) as e:
            logger.debug(f"Skipping invalid KB entry {f.name}: {e}")
    return records


def _build_doc_text(record: dict) -> str:
    """将一条历史审查记录拼接为可检索的纯文本"""
    parts: list[str] = []
    summary = record.get("summary", {})
    if summary.get("intent"):
        parts.append(summary["intent"])
    if summary.get("scope"):
        parts.append(summary["scope"])
    if summary.get("key_changes"):
        parts.extend(summary["key_changes"])
    for f in record.get("findings", []):
        if f.get("title"):
            parts.append(f["title"])
        if f.get("description"):
            parts.append(f["description"])
        if f.get("file"):
            parts.append(f["file"])
    for s in record.get("suggestions", []):
        if s.get("description"):
            parts.append(s["description"])
    # 拼接 pr_title（早期缓存可能未存 pr_title 字段）
    if record.get("pr_title"):
        parts.append(record["pr_title"])
    return " ".join(parts)


def _build_query_text(pr_metadata: PRMetadata, parsed_diff: ParsedDiff) -> str:
    """从当前 PR 元信息构建检索查询文本"""
    parts: list[str] = [pr_metadata.title, pr_metadata.description]
    # 文件路径中包含的关键标识符（去掉扩展名）也参与检索
    for f in parsed_diff.files:
        parts.append(Path(f.path).stem.replace("_", " "))
        parts.append(Path(f.path).parent.name)
    return " ".join(p for p in parts if p)


def _format_record_brief(record: dict, similarity: float) -> str:
    """格式化单条相似审查记录为上下文条目"""
    summary = record.get("summary", {})
    intent = summary.get("intent", "")
    scope = summary.get("scope", "")
    key_changes = summary.get("key_changes", [])
    findings = record.get("findings", [])

    lines = [f"- 相似度 {similarity:.2f} | 意图: {intent} | 范围: {scope}"]
    if key_changes:
        lines.append(f"  关键变更: {', '.join(key_changes[:3])}")
    if findings:
        # 仅展示前 3 条发现，避免上下文膨胀
        for f in findings[:3]:
            title = f.get("title", "")
            severity = f.get("severity", "")
            file_path = f.get("file", "")
            lines.append(f"  发现 [{severity}] {file_path}: {title}")
    return "\n".join(lines)


def search_similar_reviews(
    pr_metadata: PRMetadata,
    parsed_diff: ParsedDiff,
    top_k: int = DEFAULT_TOP_K,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
) -> list[tuple[dict, float]]:
    """检索与当前 PR 最相似的历史审查记录

    返回 [(记录, 相似度), ...] 按 similarity 降序
    """
    records = _load_knowledge_base()
    # 知识库不足时不检索：至少需要 2 条才能形成有意义的相似度对比
    if len(records) < 2:
        return []

    documents = [_tokenize(_build_doc_text(r)) for r in records]
    doc_vectors, idf = _build_tfidf_vectors(documents)
    query_vec = _to_tfidf_vector(_tokenize(_build_query_text(pr_metadata, parsed_diff)), idf)

    scored: list[tuple[dict, float]] = []
    for record, doc_vec in zip(records, doc_vectors):
        sim = _cosine_similarity(query_vec, doc_vec)
        if sim >= min_similarity:
            scored.append((record, sim))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def build_similar_reviews_context(
    pr_metadata: PRMetadata,
    parsed_diff: ParsedDiff,
    top_k: int = DEFAULT_TOP_K,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
) -> str:
    """构建相似 PR 审查经验上下文文本

    从历史审查缓存中检索 top-K 相似条目，输出经验摘要供 AI 参考。
    """
    results = search_similar_reviews(pr_metadata, parsed_diff, top_k, min_similarity)
    if not results:
        return ""

    parts = ["## 相似 PR 审查经验（基于历史审查记录的轻量 RAG 检索）"]
    for record, sim in results:
        parts.append(_format_record_brief(record, sim))

    return "\n".join(parts)
