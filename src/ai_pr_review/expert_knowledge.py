from dataclasses import dataclass, field


@dataclass
class ExpertProfile:
    name: str
    checklist: list[str]
    red_flags: list[str]
    knowledge_source: str


EXPERT_SKILLS: dict[str, ExpertProfile] = {
    "security": ExpertProfile(
        name="安全审查专家",
        knowledge_source="OWASP Code Review Guide, CWE Top 25",
        checklist=[
            "SQL注入：检查是否使用参数化查询，是否存在字符串拼接SQL",
            "XSS：检查用户输入是否经过转义/编码后输出",
            "认证/授权：检查权限校验是否完整，是否存在越权访问",
            "敏感数据：检查是否有硬编码密钥/密码/Token",
            "加密：检查是否使用不安全的加密算法(MD5/SHA1/DES)",
            "路径遍历：检查文件路径是否经过验证",
            "命令注入：检查是否安全处理外部输入传入系统命令",
            "CSRF：检查状态变更操作是否有CSRF防护",
            "不安全反序列化：检查是否安全处理反序列化输入",
            "信息泄露：检查错误信息是否暴露敏感内部信息",
        ],
        red_flags=[
            "eval() / exec() 调用",
            "直接拼接SQL语句",
            "未验证的用户输入直接使用",
            "硬编码的API Key / Secret / Password",
            "使用MD5/SHA1进行密码哈希",
            "subprocess.call with shell=True",
            "pickle.loads on untrusted data",
        ],
    ),
    "architecture": ExpertProfile(
        name="架构审查专家",
        knowledge_source="Google Code Review Guidelines, Clean Architecture",
        checklist=[
            "单一职责：函数/类是否职责清晰，是否承担过多功能",
            "耦合度：变更是否引入不必要的依赖，模块间是否松耦合",
            "抽象层次：是否存在层次穿越，抽象是否合理",
            "接口设计：API契约是否合理，参数是否过多",
            "依赖注入：是否通过依赖注入而非硬编码依赖",
            "错误处理：错误处理策略是否一致，是否吞没异常",
            "可扩展性：设计是否便于未来扩展",
        ],
        red_flags=[
            "God Class / God Function（超过100行的函数）",
            "循环依赖",
            "跨层直接调用（如Controller直接操作数据库）",
            "过多参数（超过5个）",
            "深层继承（超过3层）",
            "全局可变状态",
        ],
    ),
    "performance": ExpertProfile(
        name="性能审查专家",
        knowledge_source="性能优化最佳实践",
        checklist=[
            "N+1查询：循环中是否有数据库/网络调用",
            "内存泄漏：资源（文件/连接/句柄）是否正确释放",
            "算法复杂度：是否存在可优化的O(n²)或更高复杂度操作",
            "并发安全：共享状态是否有竞态条件",
            "缓存策略：频繁访问的数据是否有缓存",
            "懒加载：大对象是否延迟初始化",
            "批量操作：是否可以合并多次IO为批量操作",
        ],
        red_flags=[
            "循环内的数据库/网络调用",
            "未关闭的文件/连接",
            "全局可变状态",
            "无锁的并发修改",
            "大列表/字典的频繁拷贝",
            "正则表达式未预编译",
            "同步阻塞调用在异步上下文中",
        ],
    ),
    "readability": ExpertProfile(
        name="可读性审查专家",
        knowledge_source="代码大全, Google Style Guides",
        checklist=[
            "命名：变量/函数名是否表达意图，是否一致",
            "函数长度：是否超过合理范围（建议50行以内）",
            "复杂度：嵌套是否过深（建议3层以内）",
            "一致性：是否与项目现有风格一致",
            "注释：复杂逻辑是否有必要的注释，注释是否准确",
            "代码重复：是否存在可提取的重复代码",
            "魔法值：是否存在未命名的常量",
        ],
        red_flags=[
            "超过50行的函数",
            "超过3层的嵌套",
            "魔法数字/字符串",
            "过度缩写（如 a, b, tmp1）",
            "注释掉的代码块",
            "过长的条件表达式",
            "不一致的命名风格",
        ],
    ),
    "testing": ExpertProfile(
        name="测试审查专家",
        knowledge_source="测试最佳实践",
        checklist=[
            "覆盖率：新增业务逻辑是否有对应测试",
            "边界条件：是否考虑了空值/异常/极端场景",
            "测试隔离：测试是否相互独立，是否有执行顺序依赖",
            "Mock合理性：Mock是否过度/不足，是否Mock了外部依赖而非内部逻辑",
            "测试命名：测试名是否清晰表达测试意图",
            "断言质量：断言是否充分，是否只验证了关键行为",
        ],
        red_flags=[
            "无测试的新增业务逻辑",
            "仅测试正常路径（happy path）",
            "测试中硬编码外部依赖地址",
            "测试之间有执行顺序依赖",
            "过度Mock导致测试失去意义",
            "断言过于宽泛（如只检查不为None）",
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


def select_experts(file_paths: list[str], hunks_content: str) -> list[str]:
    expert_scores: dict[str, int] = {}
    combined = " ".join(file_paths).lower() + " " + hunks_content.lower()

    for keyword, experts in KEYWORD_EXPERT_MAP.items():
        if keyword in combined:
            for expert in experts:
                expert_scores[expert] = expert_scores.get(expert, 0) + 1

    if not expert_scores:
        return ["readability", "architecture"]

    sorted_experts = sorted(expert_scores.items(), key=lambda x: x[1], reverse=True)
    return [expert for expert, _ in sorted_experts[:3]]


def get_expert_profiles(expert_names: list[str]) -> list[ExpertProfile]:
    return [EXPERT_SKILLS[name] for name in expert_names if name in EXPERT_SKILLS]
