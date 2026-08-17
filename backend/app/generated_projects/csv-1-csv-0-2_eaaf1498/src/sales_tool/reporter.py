"""Report generation module.

Renders aggregation results into a Markdown daily sales report containing a
summary table, a TOP-N best-seller ranking, and data-quality notes, then
writes it to the configured output directory.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .aggregator import AggregationResult
from .parser import ParseResult, QualityIssue

DEFAULT_REPORT_FILENAME = "sales_daily_report.md"


def _fmt_number(value: float, digits: int = 2) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:,.{digits}f}"


def _fmt_percent(share: float) -> str:
    return f"{share * 100:.2f}%"


def _fmt_growth(growth: float | None) -> str:
    if growth is None:
        return "N/A"
    sign = "+" if growth > 0 else ""
    return f"{sign}{growth * 100:.2f}%"


def _render_issue(issue: QualityIssue) -> str:
    return f"- Line {issue.line} `{issue.field}`: {issue.message}"


def _render_summary_table(result: AggregationResult) -> str:
    lines = [
        "| 分类 | 销量 | 销售额 | 销售额占比 | 销量占比 | 销售额环比 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for c in result.categories:
        lines.append(
            f"| {c.category} | {_fmt_number(c.quantity)} | {_fmt_number(c.amount)} "
            f"| {_fmt_percent(c.amount_share)} | {_fmt_percent(c.quantity_share)} "
            f"| {_fmt_growth(c.mom_growth)} |"
        )
    lines.append(
        f"| **合计** | **{_fmt_number(result.totals['quantity'])}** "
        f"| **{_fmt_number(result.totals['amount'])}** | 100.00% | 100.00% | — |"
    )
    return "\n".join(lines)


def _render_top_products(result: AggregationResult, top_n: int) -> str:
    if not result.top_products:
        return "_暂无产品数据。_"
    lines = ["| 排名 | 产品名称 | 分类 | 销量 | 销售额 |", "| ---: | --- | --- | ---: | ---: |"]
    for p in result.top_products[:top_n]:
        lines.append(
            f"| {p.rank} | {p.product_name} | {p.category} "
            f"| {_fmt_number(p.quantity)} | {_fmt_number(p.amount)} |"
        )
    return "\n".join(lines)


def _render_quality_section(parse_result: ParseResult) -> str:
    total = parse_result.total_rows
    valid = parse_result.valid_count
    invalid = len(parse_result.issues)
    lines = [
        f"- 数据记录总数（含空行剔除后）：{total}",
        f"- 有效记录数：{valid}",
        f"- 问题记录数：{invalid}",
    ]
    if parse_result.issues:
        lines.append("")
        lines.append("**问题明细：**")
        lines.extend(_render_issue(i) for i in parse_result.issues)
    return "\n".join(lines)


def render_report(
    result: AggregationResult,
    parse_result: ParseResult,
    *,
    report_date: str,
    top_n: int = 5,
    report_filename: str | None = None,
) -> str:
    """Render the full Markdown report body (without writing it)."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"# 销售数据日报（{report_date}）",
        "",
        f"> 生成时间：{now} ｜ 统计窗口：`{result.report_month or 'N/A'}` "
        f"｜ 环比基准：`{result.prev_month or 'N/A'}`",
        "",
        "## 一、汇总表",
        "",
        _render_summary_table(result),
        "",
        f"## 二、TOP{top_n} 畅销产品排行",
        "",
        _render_top_products(result, top_n),
        "",
        "## 三、数据质量说明",
        "",
        _render_quality_section(parse_result),
        "",
    ]
    return "\n".join(lines)


def write_report(
    result: AggregationResult,
    parse_result: ParseResult,
    *,
    report_date: str,
    output_dir: str | Path,
    top_n: int = 5,
    report_filename: str | None = None,
) -> Path:
    """Render and write the Markdown report into `output_dir`.

    Returns:
        The path of the written report file.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = report_filename or DEFAULT_REPORT_FILENAME
    target = out_dir / filename

    body = render_report(
        result,
        parse_result,
        report_date=report_date,
        top_n=top_n,
        report_filename=report_filename,
    )
    target.write_text(body, encoding="utf-8")
    return target