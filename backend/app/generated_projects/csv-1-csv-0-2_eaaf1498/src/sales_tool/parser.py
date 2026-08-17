"""Data parsing module.

Reads a sales-record CSV, validates column/field completeness, parses the
amount and quantity fields (empty or non-numeric values are normalised to 0),
and returns a list of clean records plus a data-quality report.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

REQUIRED_COLUMNS = ["date", "category", "product_name", "quantity", "amount"]


@dataclass
class SalesRecord:
    """A single, cleaned sales record."""

    date: str
    category: str
    product_name: str
    quantity: float
    amount: float
    raw_line: int  # 1-based line number in the source CSV (header = 1)


@dataclass
class QualityIssue:
    """A data-quality problem found while parsing a row."""

    line: int
    field: str
    message: str


@dataclass
class ParseResult:
    """Output of the parsing step."""

    records: list[SalesRecord]
    issues: list[QualityIssue] = field(default_factory=list)

    @property
    def valid_count(self) -> int:
        return len(self.records)

    @property
    def total_rows(self) -> int:
        return self.valid_count + len(self.issues)


def _to_number(value: str, field_name: str, line: int, issues: list[QualityIssue]) -> float:
    """Convert a CSV cell to a float; empty/non-numeric values become 0.0."""
    stripped = value.strip()
    if stripped == "":
        return 0.0
    try:
        number = float(stripped)
        if number != number:  # NaN guard
            raise ValueError("NaN")
        return number
    except ValueError:
        issues.append(
            QualityIssue(line=line, field=field_name, message=f"non-numeric value {value!r} treated as 0")
        )
        return 0.0


def _parse_date(value: str) -> str:
    """Normalise a date cell to ISO YYYY-MM-DD; falls back to raw text."""
    stripped = value.strip()
    if not stripped:
        return ""
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(stripped, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return stripped


def parse_csv(csv_path: str | Path) -> ParseResult:
    """Parse a sales-record CSV into clean records.

    Args:
        csv_path: Path to the input CSV file.

    Returns:
        A ParseResult with cleaned records and quality issues.
    """
    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(f"Input CSV not found: {path}")

    issues: list[QualityIssue] = []
    records: list[SalesRecord] = []

    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if header is None:
            raise ValueError(f"CSV file is empty: {path}")

        header = [col.strip().lower() for col in header]
        # Map expected column names to indices (accept the standard names).
        index = {col: idx for idx, col in enumerate(header)}
        missing = [col for col in REQUIRED_COLUMNS if col not in index]
        if missing:
            raise ValueError(f"Missing required columns: {', '.join(missing)}")

        for line_no, row in enumerate(reader, start=2):
            if not row or all(cell.strip() == "" for cell in row):
                continue  # skip fully blank lines

            if len(row) < len(REQUIRED_COLUMNS):
                issues.append(
                    QualityIssue(
                        line=line_no,
                        field="<row>",
                        message=f"row has {len(row)} columns, expected {len(REQUIRED_COLUMNS)}; row skipped",
                    )
                )
                continue

            def cell(name: str) -> str:
                return row[index[name]].strip()

            date = _parse_date(cell("date"))
            category = cell("category")
            product_name = cell("product_name")

            row_errors: list[str] = []
            if not date:
                row_errors.append("missing/invalid date")
            if not category:
                row_errors.append("missing category")
            if not product_name:
                row_errors.append("missing product_name")

            if row_errors:
                issues.append(
                    QualityIssue(
                        line=line_no,
                        field="<row>",
                        message="; ".join(row_errors) + "; row skipped",
                    )
                )
                continue

            quantity = _to_number(cell("quantity"), "quantity", line_no, issues)
            amount = _to_number(cell("amount"), "amount", line_no, issues)

            records.append(
                SalesRecord(
                    date=date,
                    category=category,
                    product_name=product_name,
                    quantity=quantity,
                    amount=amount,
                    raw_line=line_no,
                )
            )

    return ParseResult(records=records, issues=issues)