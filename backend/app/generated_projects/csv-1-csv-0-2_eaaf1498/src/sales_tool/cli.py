"""Command-line entry point orchestrating the four modules."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from .aggregator import aggregate
from .parser import parse_csv
from .reporter import write_report
from .verifier import verify_and_print


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sales_tool",
        description="CSV sales data statistics tool: parse -> aggregate -> report -> verify.",
    )
    parser.add_argument(
        "-i", "--input", required=True, help="Path to the sales-record CSV file."
    )
    parser.add_argument(
        "-o", "--output", default="output", help="Directory for the generated report."
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Report date YYYY-MM-DD (default: today). Its month is the aggregation window.",
    )
    parser.add_argument(
        "--top", type=int, default=5, help="Number of best-selling products to rank (default: 5)."
    )
    parser.add_argument(
        "--report-name",
        default=None,
        help="Output report filename (default: sales_daily_report_<date>.md).",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip the acceptance verification step.",
    )
    return parser


def run(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    report_date = args.date or date.today().isoformat()
    report_month = report_date[:7]

    # 1) Data parsing
    parse_result = parse_csv(args.input)
    print(f"[parse] rows={parse_result.total_rows} valid={parse_result.valid_count} "
          f"issues={len(parse_result.issues)}")

    # 2) Aggregation
    result = aggregate(parse_result.records, report_month=report_month)
    print(f"[aggregate] categories={len(result.categories)} "
          f"amount={result.totals['amount']:.2f} quantity={result.totals['quantity']:.2f}")

    # 3) Report generation
    filename = args.report_name or f"sales_daily_report_{report_date}.md"
    report_path = write_report(
        result,
        parse_result,
        report_date=report_date,
        output_dir=args.output,
        top_n=args.top,
        report_filename=filename,
    )
    print(f"[report] written: {report_path}")

    # 4) Acceptance verification
    if not args.no_verify:
        v = verify_and_print(
            report_path,
            csv_path=args.input,
            parse_result=parse_result,
            result=result,
        )
        return 0 if v.passed else 2

    return 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()