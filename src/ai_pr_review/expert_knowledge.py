from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_pr_review.config import ProjectConfig


@dataclass
class ExpertProfile:
    name: str
    checklist: list[str]
    red_flags: list[str]
    knowledge_source: str


EXPERT_SKILLS: dict[str, ExpertProfile] = {
    "security": ExpertProfile(
        name="安全审查",
        knowledge_source="OWASP, CWE Top 25",
        checklist=[
            "SQL注入：参数化查询",
            "XSS：输入转义/编码",
            "认证授权：权限校验完整",
            "敏感数据：无硬编码密钥",
            "加密：禁止MD5/SHA1/DES",
            "路径遍历：路径验证",
            "命令注入：输入安全处理",
            "CSRF：状态变更防护",
            "反序列化：安全处理",
            "信息泄露：错误信息脱敏",
        ],
        red_flags=[
            "eval()/exec()",
            "SQL字符串拼接",
            "硬编码API Key/Password",
            "MD5/SHA1密码哈希",
            "shell=True",
            "pickle.loads(untrusted)",
        ],
    ),
    "architecture": ExpertProfile(
        name="架构审查",
        knowledge_source="Clean Architecture",
        checklist=[
            "单一职责：职责清晰",
            "耦合度：松耦合",
            "抽象层次：层次合理",
            "接口设计：契约清晰",
            "依赖注入：非硬编码",
            "错误处理：策略一致",
            "可扩展性：便于扩展",
        ],
        red_flags=[
            "God Class/Function(>100行)",
            "循环依赖",
            "跨层直接调用",
            "参数过多(>5)",
            "深层继承(>3层)",
            "全局可变状态",
        ],
    ),
    "performance": ExpertProfile(
        name="性能审查",
        knowledge_source="性能优化实践",
        checklist=[
            "N+1查询检测",
            "内存泄漏：资源释放",
            "算法复杂度优化",
            "并发安全：竞态条件",
            "缓存策略",
            "懒加载",
            "批量操作优化",
        ],
        red_flags=[
            "循环内DB/网络调用",
            "未关闭资源",
            "无锁并发修改",
            "大对象频繁拷贝",
            "正则未预编译",
            "async中同步阻塞",
        ],
    ),
    "readability": ExpertProfile(
        name="可读性审查",
        knowledge_source="代码大全, Google Style",
        checklist=[
            "命名：表达意图",
            "函数长度：<50行",
            "复杂度：嵌套<3层",
            "风格一致",
            "注释必要",
            "代码重复可提取",
            "无魔法值",
        ],
        red_flags=[
            ">50行函数",
            ">3层嵌套",
            "魔法数字",
            "过度缩写",
            "注释掉的代码",
            "过长条件表达式",
        ],
    ),
    "testing": ExpertProfile(
        name="测试审查",
        knowledge_source="测试最佳实践",
        checklist=[
            "覆盖率：业务有测试",
            "边界条件：空值/异常",
            "测试隔离：无顺序依赖",
            "Mock合理",
            "测试命名清晰",
            "断言充分",
        ],
        red_flags=[
            "新增业务无测试",
            "仅测happy path",
            "硬编码外部地址",
            "测试顺序依赖",
            "过度Mock",
            "断言过宽泛",
        ],
    ),
}

KEYWORD_EXPERT_MAP: dict[str, list[str]] = {
    "sql": ["security", "performance"],
    "database": ["security", "performance"],
    "db": ["security", "performance"],
    "query": ["security", "performance"],
    "auth": ["security"],
    "login": ["security"],
    "password": ["security"],
    "token": ["security"],
    "jwt": ["security"],
    "session": ["security"],
    "api": ["security", "architecture"],
    "route": ["security", "architecture"],
    "endpoint": ["security", "architecture"],
    "controller": ["architecture"],
    "service": ["architecture"],
    "model": ["architecture"],
    "middleware": ["security", "architecture"],
    "encrypt": ["security"],
    "decrypt": ["security"],
    "crypto": ["security"],
    "hash": ["security"],
    "test": ["testing"],
    "spec": ["testing"],
    "cache": ["performance"],
    "async": ["performance"],
    "thread": ["performance"],
    "concurrent": ["performance"],
    "pool": ["performance"],
}


def select_experts(file_paths: list[str], hunks_content: str, custom_expert_keys: list[str] | None = None) -> list[str]:
    expert_scores: dict[str, int] = {}
    combined = " ".join(file_paths).lower() + " " + hunks_content.lower()

    for keyword, experts in KEYWORD_EXPERT_MAP.items():
        if keyword in combined:
            for expert in experts:
                expert_scores[expert] = expert_scores.get(expert, 0) + 1

    if custom_expert_keys:
        for key in custom_expert_keys:
            if key not in expert_scores and key not in EXPERT_SKILLS:
                expert_scores[key] = 1

    if not expert_scores:
        return ["readability", "architecture"]

    sorted_experts = sorted(expert_scores.items(), key=lambda x: x[1], reverse=True)
    return [expert for expert, _ in sorted_experts[:3]]


def get_expert_profiles(expert_names: list[str], skills: dict[str, ExpertProfile] | None = None) -> list[ExpertProfile]:
    source = skills or EXPERT_SKILLS
    return [source[name] for name in expert_names if name in source]


def merge_expert_config(project_config: "ProjectConfig | None" = None) -> dict[str, ExpertProfile]:
    merged: dict[str, ExpertProfile] = {}
    for key, profile in EXPERT_SKILLS.items():
        merged[key] = ExpertProfile(
            name=profile.name,
            checklist=list(profile.checklist),
            red_flags=list(profile.red_flags),
            knowledge_source=profile.knowledge_source,
        )

    if not project_config:
        return merged

    for key, override in project_config.expert_overrides.items():
        if key not in merged:
            continue
        original = merged[key]
        checklist = list(original.checklist)
        red_flags = list(original.red_flags)

        if override.checklist_replace is not None:
            checklist = list(override.checklist_replace)
        elif override.checklist_append:
            checklist.extend(override.checklist_append)

        if override.red_flags_replace is not None:
            red_flags = list(override.red_flags_replace)
        elif override.red_flags_append:
            red_flags.extend(override.red_flags_append)

        merged[key] = ExpertProfile(
            name=original.name,
            checklist=checklist,
            red_flags=red_flags,
            knowledge_source=original.knowledge_source,
        )

    for key, expert_data in project_config.custom_experts.items():
        merged[key] = ExpertProfile(
            name=expert_data.get("name", key),
            checklist=expert_data.get("checklist", []),
            red_flags=expert_data.get("red_flags", []),
            knowledge_source=expert_data.get("knowledge_source", "自定义"),
        )

    return merged
