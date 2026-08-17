"""报表生成模块。

职责：
- 将统计结果渲染为 Markdown 日报表
- 包含：汇总表、TOP5 畅销产品排行、数据质量说明
- 输出到指定目录
"""

from __future__ import annotations

import datetime
import os
import re
from typing import Any, Optional

from .aggregator import ReportStats
from .parser import QualityStats


def _fmt(value: float) -> str:
    """格式化金额，保留两位小数并加千分位。"""
    return f"{value:,.2f}"


def _fmt_int(value: float) -> str:
    return f"{value:,.0f}"


def _growth_str(value: Optional[float]) -> str:
    if value is None:
        return "—"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def _render_summary_table(stats: ReportStats) -> str:
    lines = [
        "## 一、汇总表",
        "",
        "| 分类 | 销量 | 销量占比 | 环比销量 | 销售额 | 销售额占比 | 环比销售额 | 产品数 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for c in stats.categories:
        lines.append(
            "| {cat} | {qty} | {sq:.2f}% | {qg} | {amt} | {sa:.2f}% | {ag} | {pc} |".format(
                cat=c.category,
                qty=_fmt_int(c.quantity),
                sq=c.share_quantity,
                qg=_growth_str(c.quantity_growth),
                amt=_fmt(c.amount),
                sa=c.share_amount,
                ag=_growth_str(c.amount_growth),
                pc=c.product_count,
            )
        )
    lines.extend(
        [
            "| **合计** | **{qty}** | **100.00%** | — | **{amt}** | **100.00%** | — | — |".format(
                qty=_fmt_int(stats.total_quantity), amt=_fmt(stats.total_amount)
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _render_top_products(stats: ReportStats) -> str:
    lines = [
        "## 二、TOP5 畅销产品排行",
        "",
        "| 排名 | 产品 | 分类 | 销量 | 销售额 |",
        "| ---: | --- | --- | ---: | ---: |",
    ]
    for idx, p in enumerate(stats.top_products, start=1):
        lines.append(
            f"| {idx} | {p.product} | {p.category} | {_fmt_int(p.quantity)} | {_fmt(p.amount)} |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_quality_section(stats: ReportStats, quality: QualityStats) -> str:
    invalid_samples = quality.sample_invalid_rows
    sample_lines = ""
    if invalid_samples:
        sample_lines = "\n\n无效记录示例：\n"
        for s in invalid_samples:
            sample_lines += f"- 第 {s['line']} 行，缺失字段: {', '.join(s['missing_fields'])}\n"
    else:
        sample_lines = "\n"

    return (
        "## 三、数据质量说明\n\n"
        f"- 数据文件总记录数：**{quality.total_rows}**\n"
        f"- 有效记录数：**{quality.valid_rows}**\n"
        f"- 无效记录数：**{quality.invalid_rows}**（缺失必需字段）\n"
        f"- 数量字段空值按 0 处理数量：**{quality.empty_numeric_counts.get('quantity', 0)}**\n"
        f"- 金额字段空值按 0 处理数量：**{quality.empty_numeric_counts.get('amount', 0)}**\n"
        f"- 数据质量得分：**{quality.quality_score():.2f}** / 100"
        f"{sample_lines}"
    )


def render_markdown_report(
    stats: ReportStats,
    quality: QualityStats,
    source_filename: str = "sales.csv",
) -> str:
    """将统计结果渲染为 Markdown 日报表。"""
    generated_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prev_date_str = stats.prev_date or "—"
    lines = [
        "# 销售数据日报",
        "",
        f"- 数据来源：`{source_filename}`",
        f"- 报表日期：**{stats.report_date}**",
        f"- 对比日期（上一期）：{prev_date_str}",
        f"- 生成时间：{generated_at}",
        "",
        "---",
        "",
    ]
    lines.append(_render_summary_table(stats))
    lines.append(_render_top_products(stats))
    lines.append(_render_quality_section(stats, quality))
    lines.append("---")
    lines.append("")
    lines.append(f"*由 CSV 销售数据统计工具自动生成，生成时间 {generated_at}*")
    lines.append("")
    return "\n".join(lines)


def safe_report_name(date_str: str) -> str:
    """根据报表日期生成安全的文件名。"""
    clean = re.sub(r"[^\w\-]", "", date_str) or "unknown"
    return f"sales_report_{clean}.md"


def write_report(
    stats: ReportStats,
    quality: QualityStats,
    output_dir: str,
    source_filename: str = "sales.csv",
) -> str:
    """渲染并将报表写入输出目录，返回文件绝对路径。"""
    os.makedirs(output_dir, exist_ok=True)
    filename = safe_report_name(stats.report_date)
    filepath = os.path.join(output_dir, filename)
    content = render_markdown_report(stats, quality, source_filename)
    with open(filepath, "w", encoding="utf-8") as fp:
        fp.write(content)
    return filepath