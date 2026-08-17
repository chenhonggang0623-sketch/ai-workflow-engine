import re
import logging

logger = logging.getLogger(__name__)

SIMPLE_PATTERNS = [
    r"calculator",
    r"counter",
    r"todo\b",
    r"landing page",
    r"form",
    r"单页面",
    r"简单的?",
    r"生成一个",
    r"写一个",
    r"小[工具|程序|功能]",
    r"small",
    r"trivial",
    r"minor",
    r"quick",
    r"tiny",
]

MEDIUM_PATTERNS = [
    r"blog",
    r"博客",
    r"dashboard",
    r"cms",
    r"论坛",
    r"forum",
    r"多模块",
    r"system",
    r"系统",
    r"api\b",
    r"rest",
    r"crud",
    r"多人",
    r"模块",
    r"解析",
    r"聚合",
    r"统计",
    r"报表",
    r"接口",
    r"命令行",
    r"调度",
    r"定时",
    r"爬虫",
    r"自动化",
    r"pipeline",
    r"workflow",
]

COMPLEX_PATTERNS = [
    r"enterprise",
    r"企业",
    r"ecommerce",
    r"e-commerce",
    r"电商",
    r"platform",
    r"平台",
    r"microservice",
    r"分布式",
    r"high.?risk",
    r"multi.?service",
    r"production",
    r"高并发",
    r"millions?",
    r"scalab",
]

SIMPLE_AGENTS = [
    {
        "role": "developer",
        "label": "Developer",
        "system_prompt": "You are a developer. Implement the requirement directly.",
    },
]

MEDIUM_AGENTS = [
    {
        "role": "requirement_analyst",
        "label": "Requirement Analyst",
        "system_prompt": "You are a requirement analyst. Analyze and clarify the requirements.",
    },
    {
        "role": "architect",
        "label": "Architect",
        "system_prompt": "You are a software architect. Design the system architecture.",
    },
    {
        "role": "backend_developer",
        "label": "Backend Developer",
        "system_prompt": "You are a backend developer. Implement server-side logic.",
    },
    {
        "role": "frontend_developer",
        "label": "Frontend Developer",
        "system_prompt": "You are a frontend developer. Build the user interface.",
    },
    {
        "role": "tester",
        "label": "QA Tester",
        "system_prompt": "You are a QA engineer. Test the implementation thoroughly.",
    },
]

COMPLEX_AGENTS = [
    {
        "role": "product_manager",
        "label": "Product Manager",
        "system_prompt": "You are a product manager. Define requirements and acceptance criteria.",
    },
    {
        "role": "system_architect",
        "label": "System Architect",
        "system_prompt": "You are a system architect. Design the overall system architecture.",
    },
    {
        "role": "database_engineer",
        "label": "Database Engineer",
        "system_prompt": "You are a database engineer. Design and implement data models.",
    },
    {
        "role": "backend_developer",
        "label": "Backend Developer",
        "system_prompt": "You are a backend developer. Implement server-side services and APIs.",
    },
    {
        "role": "frontend_developer",
        "label": "Frontend Developer",
        "system_prompt": "You are a frontend developer. Build responsive user interfaces.",
    },
    {
        "role": "security_reviewer",
        "label": "Security Reviewer",
        "system_prompt": "You are a security engineer. Review code for vulnerabilities.",
    },
    {
        "role": "qa_engineer",
        "label": "QA Engineer",
        "system_prompt": "You are a QA engineer. Write and execute comprehensive tests.",
    },
    {
        "role": "devops_engineer",
        "label": "DevOps Engineer",
        "system_prompt": "You are a DevOps engineer. Set up CI/CD and deployment.",
    },
]


def _score_requirement(requirement: str) -> tuple[int, list[str]]:
    text = requirement.lower()
    matched = []

    score = 0

    for pattern in COMPLEX_PATTERNS:
        if re.search(pattern, text):
            score += 3
            matched.append(pattern)

    for pattern in MEDIUM_PATTERNS:
        if re.search(pattern, text):
            score += 1
            matched.append(pattern)

    for pattern in SIMPLE_PATTERNS:
        if re.search(pattern, text):
            score -= 0

    word_count = len(text.split())
    cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    word_count += cjk_chars // 2
    if word_count > 30:
        score += 1
    if word_count > 80:
        score += 1
    if word_count > 150:
        score += 1

    has_database = any(kw in text for kw in ["database", "db", "sql", "数据", "存储", "persist"])
    has_auth = any(kw in text for kw in ["auth", "login", "user", "权限", "login", "register"])
    has_external = any(kw in text for kw in ["api", "integration", "third.?party", "payment", "支付"])

    if has_database:
        score += 1
    if has_auth:
        score += 1
    if has_external:
        score += 1

    return score, matched


class ComplexityResult:
    def __init__(self, level: str, reason: str, recommended_agents: list[dict], estimated_nodes: int):
        self.level = level
        self.reason = reason
        self.recommended_agents = recommended_agents
        self.estimated_nodes = estimated_nodes

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "reason": self.reason,
            "recommended_agents": [
                {
                    "role": a["role"],
                    "label": a["label"],
                }
                for a in self.recommended_agents
            ],
            "estimated_nodes": self.estimated_nodes,
        }


class ComplexityAnalyzer:
    def analyze(self, requirement: str) -> ComplexityResult:
        score, matched = _score_requirement(requirement)

        if score >= 5:
            agents = COMPLEX_AGENTS
            level = "complex"
            reason = f"Enterprise-grade task (score={score}): multiple services, high risk, full team required."
        elif score >= 2:
            agents = MEDIUM_AGENTS
            level = "medium"
            reason = f"Multi-module task (score={score}): needs design, implementation, and testing phases."
        else:
            agents = SIMPLE_AGENTS
            level = "simple"
            reason = f"Simple task (score={score}): single agent can handle this directly."

        return ComplexityResult(
            level=level,
            reason=reason,
            recommended_agents=agents,
            estimated_nodes=len(agents),
        )
