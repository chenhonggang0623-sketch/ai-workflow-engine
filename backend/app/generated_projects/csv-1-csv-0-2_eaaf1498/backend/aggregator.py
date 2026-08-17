"""统计聚合模块。

职责：
- 按产品分类汇总销量与销售额
- 计算各分类占比
- 计算环比增长率（最新日期对比上一日期）
- 生成 TOP5 畅销产品排行
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

from .parser import ParsedData, clamp


@dataclass
class CategoryStats:
    """单个分类的统计结果。"""

    category: str
    quantity: float
    amount: float
    share_quantity: float = 0.0
    share_amount: float = 0.0
    quantity_growth: Optional[float] = None
    amount_growth: Optional[float] = None
    product_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "quantity": self.quantity,
            "amount": self.amount,
            "share_quantity": self.share_quantity,
            "share_amount": self.share_amount,
            "quantity_growth": self.quantity_growth,
            "amount_growth": self.amount_growth,
            "product_count": self.product_count,
        }


@dataclass
class ProductStats:
    """单个产品的统计结果。"""

    product: str
    category: str
    quantity: float
    amount: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "product": self.product,
            "category": self.category,
            "quantity": self.quantity,
            "amount": self.amount,
        }


@dataclass
class ReportStats:
    """整体统计结果（用于报表渲染与验收）。"""

    report_date: str
    prev_date: Optional[str]
    total_quantity: float = 0.0
    total_amount: float = 0.0
    category_count: int = 0
    product_count: int = 0
    categories: list[CategoryStats] = field(default_factory=list)
    top_products: list[ProductStats] = field(default_factory=list)
    daily_totals: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_date": self.report_date,
            "prev_date": self.prev_date,
            "total_quantity": self.total_quantity,
            "total_amount": self.total_amount,
            "category_count": self.category_count,
            "product_count": self.product_count,
            "categories": [c.to_dict() for c in self.categories],
            "top_products": [p.to_dict() for p in self.top_products],
            "daily_totals": self.daily_totals,
        }


def _build_daily_totals(data: ParsedData) -> tuple[dict[str, dict], list[dict]]:
    """按日期汇总每日销量与销售额，并返回按日期排序的总计列表。"""
    daily: dict[str, dict] = defaultdict(lambda: {"quantity": 0.0, "amount": 0.0})
    for row in data.rows:
        daily[row["date"]]["quantity"] += row["quantity"]
        daily[row["date"]]["amount"] += row["amount"]

    ordered = [
        {"date": d, "quantity": clamp(v["quantity"]), "amount": clamp(v["amount"])}
        for d, v in sorted(daily.items())
    ]
    return daily, ordered


def _growth(current: float, previous: Optional[float]) -> Optional[float]:
    """计算环比增长率（%）；无上一期数据或基数为 0 时返回 None。"""
    if previous is None or previous == 0:
        return None
    return clamp((current - previous) / previous * 100, 2)


def aggregate(data: ParsedData) -> ReportStats:
    """对解析后的数据执行统计聚合。"""
    daily, daily_totals = _build_daily_totals(data)
    dates = sorted(daily.keys())
    report_date = dates[-1] if dates else ""
    prev_date = dates[-2] if len(dates) >= 2 else None
    prev_daily = daily.get(prev_date, {"quantity": 0.0, "amount": 0.0}) if prev_date else None

    cat_agg: dict[str, dict] = defaultdict(
        lambda: {"quantity": 0.0, "amount": 0.0, "products": set()}
    )
    prod_agg: dict[str, ProductStats] = {}

    for row in data.rows:
        cat = row["category"]
        ca = cat_agg[cat]
        ca["quantity"] += row["quantity"]
        ca["amount"] += row["amount"]
        ca["products"].add(row["product"])

        key = (row["product"], cat)
        if key not in prod_agg:
            prod_agg[key] = ProductStats(
                product=row["product"],
                category=cat,
                quantity=0.0,
                amount=0.0,
            )
        prod_agg[key].quantity += row["quantity"]
        prod_agg[key].amount += row["amount"]

    # 整体总计（取最新日期当日，保证报表口径为日报）
    total_quantity = daily.get(report_date, {"quantity": 0.0})["quantity"]
    total_amount = daily.get(report_date, {"amount": 0.0})["amount"]

    categories: list[CategoryStats] = []
    for cat, agg in cat_agg.items():
        categories.append(
            CategoryStats(
                category=cat,
                quantity=agg["quantity"],
                amount=clamp(agg["amount"]),
                product_count=len(agg["products"]),
            )
        )
    # 只保留报表当日的分类数据，保证“环比/占比”口径与日报一致
    report_categories: dict[str, dict] = defaultdict(
        lambda: {"quantity": 0.0, "amount": 0.0, "products": set()}
    )
    for row in data.rows:
        if row["date"] == report_date:
            cat = row["category"]
            rc = report_categories[cat]
            rc["quantity"] += row["quantity"]
            rc["amount"] += row["amount"]
            rc["products"].add(row["product"])

    categories = [
        CategoryStats(
            category=cat,
            quantity=clamp(agg["quantity"]),
            amount=clamp(agg["amount"]),
            product_count=len(agg["products"]),
        )
        for cat, agg in sorted(report_categories.items())
    ]

    total_q = total_quantity or 1.0
    total_a = total_amount or 1.0
    for cs in categories:
        cs.share_quantity = clamp(cs.quantity / total_q * 100, 2)
        cs.share_amount = clamp(cs.amount / total_a * 100, 2)
        if prev_daily is not None:
            cs.quantity_growth = _growth(cs.quantity, prev_daily["quantity"])
            cs.amount_growth = _growth(cs.amount, prev_daily["amount"])

    top_products = sorted(
        prod_agg.values(),
        key=lambda p: (p.amount, p.quantity),
        reverse=True,
    )[:5]

    return ReportStats(
        report_date=report_date,
        prev_date=prev_date,
        total_quantity=clamp(total_quantity),
        total_amount=clamp(total_amount),
        category_count=len(categories),
        product_count=len(prod_agg),
        categories=categories,
        top_products=top_products,
        daily_totals=daily_totals,
    )