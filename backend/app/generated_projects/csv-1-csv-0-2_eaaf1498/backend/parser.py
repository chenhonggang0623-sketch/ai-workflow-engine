"""数据解析模块。

职责：
- 读取销售记录 CSV 文件
- 校验字段完整性（表头是否包含必需列）
- 解析金额与数量字段，空值按 0 处理
- 产出结构化数据与数据质量统计
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass, field
from typing import Any, Optional

REQUIRED_COLUMNS = ["date", "category", "product", "quantity", "amount"]
NUMERIC_COLUMNS = {"quantity", "amount"}


class CsvParseError(Exception):
    """CSV 解析或字段校验失败时抛出。"""


@dataclass
class QualityStats:
    """数据质量统计。"""

    total_rows: int = 0
    valid_rows: int = 0
    invalid_rows: int = 0
    empty_numeric_counts: dict[str, int] = field(default_factory=dict)
    missing_field_rows: int = 0
    sample_invalid_rows: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_rows": self.total_rows,
            "valid_rows": self.valid_rows,
            "invalid_rows": self.invalid_rows,
            "missing_field_rows": self.missing_field_rows,
            "empty_numeric_counts": dict(self.empty_numeric_counts),
            "sample_invalid_rows": self.sample_invalid_rows[:5],
            "quality_score": self.quality_score(),
        }

    def quality_score(self) -> float:
        """数据质量得分：有效行占比（0-100）。"""
        if self.total_rows <= 0:
            return 0.0
        return round(self.valid_rows / self.total_rows * 100, 2)


@dataclass
class ParsedData:
    """解析后的结构化数据。"""

    header: list[str]
    rows: list[dict[str, Any]]
    quality: QualityStats

    def to_dict(self) -> dict[str, Any]:
        return {
            "header": self.header,
            "rows": self.rows,
            "quality": self.quality.to_dict(),
        }


def _safe_float(value: Any) -> tuple[float, bool]:
    """解析金额/数量字段；空值按 0 处理。返回 (数值, 是否为空)。"""
    if value is None:
        return 0.0, True
    text = str(value).strip()
    if text == "":
        return 0.0, True
    try:
        return float(text), False
    except ValueError:
        return 0.0, False


def parse_csv_source(source: str) -> ParsedData:
    """从 CSV 文本解析销售记录。

    参数:
        source: CSV 文件内容（UTF-8 文本）

    返回:
        ParsedData: 结构化数据与质量统计

    异常:
        CsvParseError: 表头缺失必需字段或 CSV 结构非法
    """
    try:
        reader = csv.DictReader(io.StringIO(source))
        header = reader.fieldnames or []
    except csv.Error as exc:
        raise CsvParseError(f"无法解析 CSV: {exc}") from exc

    if not header:
        raise CsvParseError("CSV 文件为空或缺少表头")

    missing = [col for col in REQUIRED_COLUMNS if col not in header]
    if missing:
        raise CsvParseError(
            f"字段校验失败，缺少必需列: {', '.join(missing)}；"
            f"必需列为: {', '.join(REQUIRED_COLUMNS)}"
        )

    quality = QualityStats(empty_numeric_counts={c: 0 for c in NUMERIC_COLUMNS})
    rows: list[dict[str, Any]] = []

    for idx, raw in enumerate(reader, start=2):
        quality.total_rows += 1
        missing_fields = [col for col in REQUIRED_COLUMNS if not str(raw.get(col) or "").strip()]
        record: dict[str, Any] = {}
        row_ok = True

        if missing_fields:
            quality.missing_field_rows += 1
            quality.invalid_rows += 1
            row_ok = False
            if len(quality.sample_invalid_rows) < 5:
                quality.sample_invalid_rows.append(
                    {"line": idx, "missing_fields": missing_fields, "raw": dict(raw)}
                )

        for col in REQUIRED_COLUMNS:
            value = raw.get(col, "")
            if col in NUMERIC_COLUMNS:
                num, empty = _safe_float(value)
                if empty:
                    quality.empty_numeric_counts[col] += 1
                record[col] = num
            else:
                record[col] = str(value or "").strip()

        if row_ok:
            quality.valid_rows += 1
        rows.append(record)

    return ParsedData(header=header, rows=rows, quality=quality)


def parse_csv_file(filepath: str) -> ParsedData:
    """从文件路径读取并解析 CSV。"""
    try:
        with open(filepath, "r", encoding="utf-8-sig") as fp:
            source = fp.read()
    except OSError as exc:
        raise CsvParseError(f"无法读取文件 {filepath}: {exc}") from exc
    return parse_csv_source(source)


def clamp(value: float, digits: int = 2) -> float:
    """四舍五入保留指定小数位。"""
    if math.isnan(value) or math.isinf(value):
        return 0.0
    return round(value, digits)