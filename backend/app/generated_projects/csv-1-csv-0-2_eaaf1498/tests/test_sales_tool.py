"""Unit tests for the CSV sales statistics tool."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sales_tool.aggregator import aggregate
from sales_tool.parser import parse_csv
from sales_tool.reporter import render_report, write_report
from sales_tool.verifier import REQUIRED_SECTIONS, verify_report

SAMPLE = """
date,category,product_name,quantity,amount
2026-07-01,电子,无线耳机,30,8970
2026-07-15,电子,无线耳机,40,11960
2026-07-02,食品,咖啡豆,120,5760
2026-08-01,电子,无线耳机,45,13455
2026-08-10,电子,智能手表,20,9980
2026-08-11,食品,咖啡豆,160,7680
2026-08-12,电子,,50,2000
"""


class ParserTest(unittest.TestCase):
    def test_parse_empty_values_become_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sales.csv"
            path.write_text("date,category,product_name,quantity,amount\n2026-08-01,电子,无线耳机,,10\n")
            result = parse_csv(path)
            self.assertEqual(result.valid_count, 1)
            self.assertEqual(result.records[0].quantity, 0.0)
            self.assertEqual(result.records[0].amount, 10.0)

    def test_parse_non_numeric_becomes_zero_and_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sales.csv"
            path.write_text(
                "date,category,product_name,quantity,amount\n2026-08-01,电子,无线耳机,abc,10\n"
            )
            result = parse_csv(path)
            self.assertEqual(result.records[0].quantity, 0.0)
            self.assertEqual(len(result.issues), 1)
            self.assertEqual(result.issues[0].field, "quantity")

    def test_parse_skips_rows_missing_critical_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sales.csv"
            path.write_text("date,category,product_name,quantity,amount\n2026-08-01,电子,,10,10\n")
            result = parse_csv(path)
            self.assertEqual(result.valid_count, 0)
            self.assertEqual(len(result.issues), 1)

    def test_parse_missing_required_column_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sales.csv"
            path.write_text("date,category,quantity,amount\n2026-08-01,电子,10,10\n")
            with self.assertRaises(ValueError):
                parse_csv(path)

    def test_parse_header_case_insensitive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sales.csv"
            path.write_text(
                "Date,Category,Product_Name,Quantity,Amount\n2026-08-01,电子,无线耳机,5,25\n"
            )
            result = parse_csv(path)
            self.assertEqual(result.valid_count, 1)
            self.assertEqual(result.records[0].product_name, "无线耳机")


class AggregatorTest(unittest.TestCase):
    def _records(self) -> list:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sales.csv"
            path.write_text(SAMPLE)
            return parse_csv(path).records

    def test_category_totals_and_shares(self) -> None:
        result = aggregate(self._records(), report_month="2026-08")
        by_cat = {c.category: c for c in result.categories}
        # 电子: 30+40+45+20+50 = 185 qty, 8970+11960+13455+9980+2000 = 46365
        self.assertAlmostEqual(by_cat["电子"].quantity, 185)
        self.assertAlmostEqual(by_cat["电子"].amount, 46365)
        # 食品: 120+160 = 280 qty, 5760+7680 = 13440
        self.assertAlmostEqual(by_cat["食品"].quantity, 280)
        self.assertAlmostEqual(by_cat["食品"].amount, 13440)
        total_amount = 46365 + 13440
        self.assertAlmostEqual(by_cat["电子"].amount_share, 46365 / total_amount)
        self.assertAlmostEqual(by_cat["食品"].amount_share, 13440 / total_amount)

    def test_mom_growth(self) -> None:
        result = aggregate(self._records(), report_month="2026-08")
        by_cat = {c.category: c for c in result.categories}
        # 电子 August vs July: (45405 - 20930) / 20930
        self.assertAlmostEqual(by_cat["电子"].mom_growth, (45405 - 20930) / 20930)
        # 食品 August vs July: (7680 - 5760) / 5760
        self.assertAlmostEqual(by_cat["食品"].mom_growth, (7680 - 5760) / 5760)

    def test_top_products_sorted_by_amount(self) -> None:
        result = aggregate(self._records(), report_month="2026-08")
        amounts = [p.amount for p in result.top_products]
        self.assertEqual(amounts, sorted(amounts, reverse=True))
        self.assertEqual(result.top_products[0].product_name, "无线耳机")

    def test_empty_input(self) -> None:
        result = aggregate([], report_month="2026-08")
        self.assertEqual(result.categories, [])
        self.assertEqual(result.totals["amount"], 0.0)


class ReporterTest(unittest.TestCase):
    def test_render_contains_all_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sales.csv"
            path.write_text(SAMPLE)
            parsed = parse_csv(path)
            result = aggregate(parsed.records, report_month="2026-08")
            body = render_report(result, parsed, report_date="2026-08-17")
            for section in REQUIRED_SECTIONS:
                self.assertIn(section, body)
            self.assertIn("TOP5", body)

    def test_write_report_creates_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "sales.csv"
            src.write_text(SAMPLE)
            parsed = parse_csv(src)
            result = aggregate(parsed.records, report_month="2026-08")
            out_dir = Path(tmp) / "out"
            target = write_report(
                result, parsed, report_date="2026-08-17", output_dir=out_dir
            )
            self.assertTrue(target.is_file())
            self.assertIn("# 销售数据日报", target.read_text(encoding="utf-8"))


class VerifierTest(unittest.TestCase):
    def test_verify_passes_on_generated_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "sales.csv"
            src.write_text(SAMPLE)
            parsed = parse_csv(src)
            result = aggregate(parsed.records, report_month="2026-08")
            out_dir = Path(tmp) / "out"
            target = write_report(
                result, parsed, report_date="2026-08-17", output_dir=out_dir
            )
            v = verify_report(target, csv_path=src, parse_result=parsed, result=result)
            self.assertTrue(v.passed, msg=f"failures: {v.failures}")

    def test_verify_fails_when_report_missing(self) -> None:
        v = verify_report(Path("/nonexistent/report.md"), csv_path=None)
        self.assertFalse(v.exists)
        self.assertFalse(v.passed)

    def test_verify_detects_value_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "sales.csv"
            src.write_text(SAMPLE)
            parsed = parse_csv(src)
            result = aggregate(parsed.records, report_month="2026-08")
            out_dir = Path(tmp) / "out"
            target = write_report(
                result, parsed, report_date="2026-08-17", output_dir=out_dir
            )
            target.write_text(target.read_text(encoding="utf-8").replace("13455", "99999"), encoding="utf-8")
            v = verify_report(target, csv_path=src, parse_result=parsed, result=result)
            self.assertFalse(v.passed)
            self.assertTrue(any("value" in f for f in v.failures))


if __name__ == "__main__":
    unittest.main()