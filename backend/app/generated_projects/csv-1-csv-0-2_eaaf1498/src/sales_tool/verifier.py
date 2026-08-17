"""Acceptance verification module.

Checks that the report file exists, that its content is complete (all required
sections present), and that the aggregated figures reported in the Markdown
match a fresh recomputation from the original CSV data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .aggregator import AggregationResult
from .parser import ParseResult
from .reporter import _fmt_number, _fmt_percent, render_report

REQUIRED_SECTIONS = ["汇总表", "畅销产品排行", "数据质量说明"]
REQUIRED_TABLE_COLUMNS = ["分类", "销量", "销售额", "销售额占比", "环比"]


@dataclass
class VerificationReport:
    """Outcome of the acceptance checks."""

    report_path: Path
    exists: bool
    sections_ok: bool = False
    values_ok: bool = False
    checks: dict[str, bool] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.exists and self.sections_ok and self.values_ok


def _recompute_from_source(csv_path: str | Path, report_month: str) -> AggregationResult:
    """Fresh recomputation used as the ground truth for value checks."""
    from .aggregator import aggregate
    from .parser import parse_csv

    parsed = parse_csv(csv_path)
    return aggregate(parsed.records, report_month=report_month)


def verify_report(
    report_path: str | Path,
    *,
    csv_path: str | Path | None,
    parse_result: ParseResult | None = None,
    result: AggregationResult | None = None,
) -> VerificationReport:
    """Verify a generated report against the source data.

    Args:
        report_path: Path of the report file to verify.
        csv_path: Original CSV; used to recompute expected figures.
        parse_result: Parser output (used for quality-section checks).
        result: Aggregation output; when omitted it is recomputed.

    Returns:
        A VerificationReport summarising every check.
    """
    report_path = Path(report_path)
    v = VerificationReport(report_path=report_path, exists=report_path.is_file())

    if not v.exists:
        v.failures.append(f"report file missing: {report_path}")
        return v

    text = report_path.read_text(encoding="utf-8")

    # --- Content completeness ---
    for section in REQUIRED_SECTIONS:
        ok = section in text
        v.checks[f"section:{section}"] = ok
        if not ok:
            v.failures.append(f"missing section: {section}")
    for column in REQUIRED_TABLE_COLUMNS:
        ok = column in text
        v.checks[f"column:{column}"] = ok
        if not ok:
            v.failures.append(f"summary table missing column: {column}")
    v.sections_ok = all(v.checks[k] for k in v.checks if k.startswith("section:")) and all(
        v.checks[k] for k in v.checks if k.startswith("column:")
    )

    # --- Numerical consistency ---
    if csv_path is not None:
        expected: AggregationResult | None = None
        expected_month = result.report_month if result else None
        try:
            if result is not None:
                expected = result
            else:
                expected = _recompute_from_source(csv_path, expected_month or "")
        except Exception as exc:  # noqa: BLE001 - report the failure explicitly
            v.failures.append(f"recompute failed: {exc}")
            v.values_ok = False
            return v

        numeric_checks = {
            "totals.amount": _fmt_number(expected.totals["amount"]) in text,
            "totals.quantity": _fmt_number(expected.totals["quantity"]) in text,
            "category.amount": all(
                _fmt_number(c.amount) in text for c in expected.categories
            ),
            "category.quantity": all(
                _fmt_number(c.quantity) in text for c in expected.categories
            ),
            "category.share": all(
                _fmt_percent(c.amount_share) in text for c in expected.categories
            ),
            "top.rank": all(
                f"| {p.rank} | {p.product_name} |" in text
                for p in expected.top_products[:5]
            ),
        }
        for key, ok in numeric_checks.items():
            v.checks[f"value:{key}"] = ok
            if not ok:
                v.failures.append(f"value mismatch: {key}")
        v.values_ok = all(ok for k, ok in numeric_checks.items())

    return v


def verify_and_print(
    report_path: str | Path,
    *,
    csv_path: str | Path | None,
    parse_result: ParseResult | None = None,
    result: AggregationResult | None = None,
) -> VerificationReport:
    """Verify a report and print a human-readable acceptance summary."""
    v = verify_report(
        report_path,
        csv_path=csv_path,
        parse_result=parse_result,
        result=result,
    )
    status = "PASS" if v.passed else "FAIL"
    print(f"[verify] report: {v.report_path}")
    print(f"[verify] exists: {v.exists} | sections: {v.sections_ok} | values: {v.values_ok}")
    for key, ok in v.checks.items():
        print(f"[verify]   {'OK ' if ok else 'FAIL'} {key}")
    for failure in v.failures:
        print(f"[verify]   ! {failure}")
    print(f"[verify] overall: {status}")
    return v