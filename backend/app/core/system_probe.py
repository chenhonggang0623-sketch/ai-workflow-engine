"""本机资源探测与执行预算推荐。

纯函数为主,便于单测;psutil 不可用时降级为只报 CPU 核数。
"""

import os
from typing import Any

try:
    import psutil
except ImportError:  # pragma: no cover - 依赖缺失降级路径
    psutil = None  # type: ignore[assignment]


def detect_hardware() -> dict[str, Any]:
    """返回本机 CPU 核数 / 内存 / 平台。psutil 缺失时内存记为 0。"""
    cpu_count = os.cpu_count() or 1
    memory_bytes: int = 0
    if psutil is not None:
        try:
            memory_bytes = psutil.virtual_memory().total
        except Exception:
            memory_bytes = 0
    return {
        "cpu_count": cpu_count,
        "memory_gb": round(memory_bytes / (1024**3), 1),
        "memory_bytes": memory_bytes,
        "platform": os.sys.platform,
    }


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def _memory_tier_nodes(memory_gb: float) -> int:
    """按内存档位封顶节点数:8GB 以下 16、16GB 以下 32、以上 64。"""
    if memory_gb <= 0:
        return 32
    if memory_gb < 8:
        return 16
    if memory_gb < 16:
        return 32
    return 64


def recommend_limits(hardware: dict[str, Any]) -> dict[str, Any]:
    """根据本机配置计算执行预算推荐值。

    规则:
    - max_concurrency = clamp(cpu_count // 2, 2, 16):留一半核给系统/DB/浏览器
    - dag_max_nodes = clamp(cpu_count * 8, 16, 64),再按内存档位封顶
    - dag_max_edges = dag_max_nodes * 3
    - fan_in/fan_out 沿用既有默认 8/6
    - cpu_usage_cap_percent = 75
    """
    cpu_count = int(hardware.get("cpu_count") or 1)
    memory_gb = float(hardware.get("memory_gb") or 0)

    max_nodes = _clamp(cpu_count * 8, 16, 64)
    max_nodes = min(max_nodes, _memory_tier_nodes(memory_gb))

    return {
        "max_concurrency": _clamp(cpu_count // 2, 2, 16),
        "dag_max_nodes": max_nodes,
        "dag_max_edges": max_nodes * 3,
        "dag_max_fan_in": 8,
        "dag_max_fan_out": 6,
        "cpu_usage_cap_percent": 75,
    }


def recommended_base(limits: dict[str, Any]) -> int:
    """取推荐值中的并发基准(供 ResourceMonitor 兜底)。"""
    return int(limits.get("max_concurrency") or 2)