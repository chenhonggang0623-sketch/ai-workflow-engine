"""验收模块。

职责：
- 校验报表文件已生成且内容完整
- 校验统计数值与原始数据一致
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional

from .aggregator import ReportStats


@dataclass
class ValidationResult:
    """验收结果。"""

    passed: bool
    checks: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "checks": self.checks}


def _check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": passed, "detail": detail}


def validate_report(
    report_path: str,
    stats: ReportStats,
) -> ValidationResult:
    """校验报表文件是否生成、内容完整且数值与统计结果一致。"""
    checks: list[dict[str, Any]] = []

    # 1) 文件已生成
    exists = os.path.isfile(report_path)
    checks.append(
        _check(
            "报表文件已生成",
            exists,
            f"路径: {report_path}" if exists else f"文件不存在: {report_path}",
        )
    )
    if not exists:
        return ValidationResult(passed=False, checks=checks)

    with open(report_path, "r", encoding="utf-8") as fp:
        content = fp.read()

    # 2) 内容完整：关键小节齐全
    sections = {
        "汇总表": "一、汇总表",
        "TOP5 畅销产品排行": "二、TOP5 畅销产品排行",
        "数据质量说明": "三、数据质量说明",
    }
    for name, keyword in sections.items():
        checks.append(
            _check(f"包含小节「{name}」", keyword in content, f"关键字: {keyword}")
        )

    # 3) 数值一致性：合计金额与销量必须与统计结果一致
    total_amount_str = f"{stats.total_amount:,.2f}"
    total_qty_str = f"{stats.total_quantity:,.0f}"
    checks.append(
        _check(
            "合计销售额与统计一致",
            total_amount_str in content,
            f"期望合计销售额: {total_amount_str}",
        )
    )
    checks.append(
        _check(
            "合计销量与统计一致",
            total_qty_str in content,
            f"期望合计销量: {total_qty_str}",
        )
    )

    # 4) TOP5 排行条数校验
    top_count = content.count("| 排名 |") > 0 and sum(
        1 for line in content.splitlines() if line.startswith("| ") and line.split("|")[1].strip().isdigit()
    )
    checks.append(
        _check(
            "TOP5 排行存在",
            top_count >= 1 and len(stats.top_products) <= 5,
            f"排行条数: {len(stats.top_products)}",
        )
    )

    passed = all(c["passed"] for c in checks)
    return ValidationResult(passed=passed, checks=checks)