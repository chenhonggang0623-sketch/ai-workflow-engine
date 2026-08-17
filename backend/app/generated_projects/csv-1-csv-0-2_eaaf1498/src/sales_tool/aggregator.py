"""Statistics aggregation module.

Aggregates cleaned sales records by product category (total quantity, total
amount, amount share, and month-over-month amount growth), and computes the
TOP-N best-selling products by sales amount.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

from .parser import SalesRecord

# Sales generated outside a recognised month window are not included in the
# month-over-month growth computation, only in the period totals.
UNKNOWN_MONTH = ""


@dataclass
class CategoryStats:
    """Aggregated statistics for one product category."""

    category: str
    quantity: float
    amount: float
    amount_share: float  # 0..1 fraction of total amount
    quantity_share: float  # 0..1 fraction of total quantity
    mom_growth: float | None  # fraction growth vs previous month, None if N/A


@dataclass
class ProductRank:
    """One row of the TOP-N best-seller ranking."""

    rank: int
    product_name: str
    category: str
    quantity: float
    amount: float


@dataclass
class AggregationResult:
    """Output of the aggregation step."""

    categories: list[CategoryStats]
    top_products: list[ProductRank]
    totals: dict[str, float]  # {"quantity": .., "amount": ..}
    report_month: str  # YYYY-MM of the reporting window ("" if none)
    prev_month: str  # YYYY-MM of the comparison window ("" if none)
    period_unknown_records: int = field(default=0)


def _month_key(date_str: str) -> str:
    """Extract the YYYY-MM month key from an ISO date string."""
    return date_str[:7] if len(date_str) >= 7 else UNKNOWN_MONTH


def _safe_growth(current: float, previous: float) -> float | None:
    """Compute the MoM growth fraction; None when it cannot be computed."""
    if previous == 0:
        return None if current == 0 else None  # undefined baseline
    return (current - previous) / previous


def _shift_month(month: str, delta: int) -> str | None:
    """Add `delta` months to a YYYY-MM string. Returns None on parse failure."""
    try:
        year, m = (int(p) for p in month.split("-"))
    except (ValueError, AttributeError):
        return None
    index = year * 12 + (m - 1) + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def aggregate(records: Iterable[SalesRecord], report_month: str | None = None) -> AggregationResult:
    """Aggregate cleaned sales records by category.

    Args:
        records: Cleaned sales records from the parser.
        report_month: YYYY-MM window used for month-over-month growth. When
            None it is inferred as the most recent month present in the data.

    Returns:
        AggregationResult with per-category stats, TOP-N products and totals.
    """
    records = list(records)
    if not records:
        return AggregationResult(
            categories=[],
            top_products=[],
            totals={"quantity": 0.0, "amount": 0.0},
            report_month=UNKNOWN_MONTH,
            prev_month=UNKNOWN_MONTH,
        )

    # Infer the report month from the data if not supplied.
    if report_month is None:
        months = {_month_key(r.date) for r in records if _month_key(r.date)}
        report_month = max(months) if months else UNKNOWN_MONTH
    prev_month = _shift_month(report_month, -1) if report_month else UNKNOWN_MONTH

    # Per-category totals for the whole dataset.
    cat_total: dict[str, dict[str, float]] = defaultdict(lambda: {"quantity": 0.0, "amount": 0.0})
    # Per-category totals split by month (for MoM).
    cat_month: dict[str, dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: {"quantity": 0.0, "amount": 0.0})
    )
    # Per-product totals for ranking.
    product_total: dict[str, dict[str, float]] = defaultdict(
        lambda: {"quantity": 0.0, "amount": 0.0, "category": ""}
    )

    for rec in records:
        cat_total[rec.category]["quantity"] += rec.quantity
        cat_total[rec.category]["amount"] += rec.amount

        month = _month_key(rec.date)
        if month:
            cat_month[rec.category][month]["quantity"] += rec.quantity
            cat_month[rec.category][month]["amount"] += rec.amount

        key = rec.product_name
        product_total[key]["quantity"] += rec.quantity
        product_total[key]["amount"] += rec.amount
        product_total[key]["category"] = rec.category

    total_quantity = sum(c["quantity"] for c in cat_total.values())
    total_amount = sum(c["amount"] for c in cat_total.values())

    categories: list[CategoryStats] = []
    for category in sorted(cat_total):
        c = cat_total[category]
        current = cat_month[category].get(report_month, {"quantity": 0.0, "amount": 0.0})
        previous = cat_month[category].get(prev_month, {"quantity": 0.0, "amount": 0.0})
        growth = None
        if report_month and prev_month:
            # Only meaningful when the category traded in the current window.
            if current["amount"] != 0 or previous["amount"] != 0:
                if previous["amount"] == 0:
                    growth = None  # undefined baseline, reported as N/A
                else:
                    growth = _safe_growth(current["amount"], previous["amount"])
        categories.append(
            CategoryStats(
                category=category,
                quantity=c["quantity"],
                amount=c["amount"],
                amount_share=(c["amount"] / total_amount) if total_amount else 0.0,
                quantity_share=(c["quantity"] / total_quantity) if total_quantity else 0.0,
                mom_growth=growth,
            )
        )

    ranked = sorted(
        product_total.items(), key=lambda kv: (kv[1]["amount"], kv[1]["quantity"]), reverse=True
    )
    top_products = [
        ProductRank(
            rank=i,
            product_name=name,
            category=info["category"],
            quantity=info["quantity"],
            amount=info["amount"],
        )
        for i, (name, info) in enumerate(ranked, start=1)
    ]

    period_unknown = sum(1 for r in records if _month_key(r.date) == UNKNOWN_MONTH)

    return AggregationResult(
        categories=categories,
        top_products=top_products,
        totals={"quantity": total_quantity, "amount": total_amount},
        report_month=report_month,
        prev_month=prev_month,
        period_unknown_records=period_unknown,
    )