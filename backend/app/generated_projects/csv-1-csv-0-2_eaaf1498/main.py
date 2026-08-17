"""CSV 销售数据统计工具 - 命令行入口。

用法:
    python main.py <input.csv> [--output <dir>] [--no-validate] [--serve] [--port 8000]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.pipeline import run_pipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="CSV 销售数据统计工具")
    parser.add_argument("input", nargs="?", help="销售记录 CSV 文件路径")
    parser.add_argument("--output", "-o", default="reports", help="报表输出目录（默认 reports）")
    parser.add_argument("--no-validate", action="store_true", help="跳过验收步骤")
    parser.add_argument("--serve", action="store_true", help="启动 Web UI 服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    args = parser.parse_args()

    if args.serve:
        from backend.server import run_server

        print(f"正在启动 Web 服务: http://{args.host}:{args.port}")
        run_server(args.host, args.port)
        return 0

    if not args.input:
        parser.print_help()
        return 2

    if not Path(args.input).is_file():
        print(f"[错误] 输入文件不存在: {args.input}", file=sys.stderr)
        return 1

    result = run_pipeline(
        args.input,
        args.output,
        source_filename=Path(args.input).name,
        validate=not args.no_validate,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    stats = result["stats"]
    quality = result["parsed"]["quality"]
    print("=" * 56)
    print("  CSV 销售数据统计工具 - 处理完成")
    print("=" * 56)
    print(f"  报表日期    : {stats['report_date']}")
    print(f"  总销量      : {stats['total_quantity']:,.0f}")
    print(f"  总销售额    : {stats['total_amount']:,.2f}")
    print(f"  分类数      : {stats['category_count']}")
    print(f"  产品数      : {stats['product_count']}")
    print(f"  有效记录    : {quality['valid_rows']}/{quality['total_rows']}")
    print(f"  数据质量得分: {quality['quality_score']:.2f}/100")
    print(f"  报表路径    : {result['report_path']}")
    if "validation" in result:
        ok = result["validation"]["passed"]
        print(f"  验收结果    : {'通过' if ok else '未通过'}")
    return 0 if result.get("validation", {}).get("passed", True) else 3


if __name__ == "__main__":
    sys.exit(main())