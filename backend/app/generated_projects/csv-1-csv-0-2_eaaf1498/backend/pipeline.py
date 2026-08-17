"""流水线编排：解析 → 聚合 → 报表 → 验收。"""

from __future__ import annotations

import os
from typing import Any

from .aggregator import aggregate
from .parser import ParsedData, parse_csv_file, parse_csv_source
from .report import write_report
from .validator import validate_report


def run_pipeline(
    source: str,
    output_dir: str,
    source_filename: str = "sales.csv",
    validate: bool = True,
) -> dict[str, Any]:
    """执行完整统计流水线并返回结果。

    参数:
        source: CSV 内容或文件路径
        output_dir: 报表输出目录
        source_filename: 报表中展示的数据来源名
        validate: 是否执行验收

    返回:
        dict: 包含解析、统计、报表路径与验收结果
    """
    if os.path.isfile(source):
        parsed = parse_csv_file(source)
    else:
        parsed = parse_csv_source(source)

    stats = aggregate(parsed)
    report_path = write_report(stats, parsed.quality, output_dir, source_filename)

    result: dict[str, Any] = {
        "parsed": parsed.to_dict(),
        "stats": stats.to_dict(),
        "report_path": report_path,
        "report_filename": os.path.basename(report_path),
    }
    if validate:
        validation = validate_report(report_path, stats)
        result["validation"] = validation.to_dict()
    return result


def run_pipeline_from_parsed(
    parsed: ParsedData,
    output_dir: str,
    source_filename: str = "sales.csv",
    validate: bool = True,
) -> dict[str, Any]:
    """从已解析数据执行统计流水线（供服务端使用）。"""
    stats = aggregate(parsed)
    report_path = write_report(stats, parsed.quality, output_dir, source_filename)
    result: dict[str, Any] = {
        "parsed": parsed.to_dict(),
        "stats": stats.to_dict(),
        "report_path": report_path,
        "report_filename": os.path.basename(report_path),
    }
    if validate:
        result["validation"] = validate_report(report_path, stats).to_dict()
    return result