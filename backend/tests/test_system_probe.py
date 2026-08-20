import pytest

from app.core.system_probe import detect_hardware, recommend_limits, recommended_base


def test_recommend_limits_low_cpu():
    hw = {"cpu_count": 2, "memory_gb": 4.0, "platform": "test"}
    r = recommend_limits(hw)
    assert r["max_concurrency"] == 2
    assert r["dag_max_nodes"] == 16
    assert r["dag_max_edges"] == 48
    assert r["dag_max_fan_in"] == 8
    assert r["dag_max_fan_out"] == 6
    assert r["cpu_usage_cap_percent"] == 75


def test_recommend_limits_mid_cpu():
    hw = {"cpu_count": 8, "memory_gb": 15.9, "platform": "test"}
    r = recommend_limits(hw)
    assert r["max_concurrency"] == 4
    assert r["dag_max_nodes"] == 32  # cpu*8=64, 内存 <16GB 封顶 32
    assert r["dag_max_edges"] == 96


def test_recommend_limits_high_cpu():
    hw = {"cpu_count": 16, "memory_gb": 32.0, "platform": "test"}
    r = recommend_limits(hw)
    assert r["max_concurrency"] == 8
    assert r["dag_max_nodes"] == 64
    assert r["dag_max_edges"] == 192


def test_recommend_limits_concurrency_cap_16():
    hw = {"cpu_count": 64, "memory_gb": 128.0, "platform": "test"}
    r = recommend_limits(hw)
    assert r["max_concurrency"] == 16
    assert r["dag_max_nodes"] == 64


def test_recommend_limits_memory_tier_8gb():
    hw = {"cpu_count": 16, "memory_gb": 6.0, "platform": "test"}
    r = recommend_limits(hw)
    assert r["dag_max_nodes"] == 16


def test_recommend_limits_memory_tier_16gb():
    hw = {"cpu_count": 16, "memory_gb": 10.0, "platform": "test"}
    r = recommend_limits(hw)
    assert r["dag_max_nodes"] == 32


def test_recommend_limits_no_memory_info():
    hw = {"cpu_count": 16, "memory_gb": 0, "platform": "test"}
    r = recommend_limits(hw)
    assert r["dag_max_nodes"] == 32  # 内存未知走默认档


def test_recommend_limits_single_core():
    hw = {"cpu_count": 1, "memory_gb": 2.0, "platform": "test"}
    r = recommend_limits(hw)
    assert r["max_concurrency"] == 2  # 下限 2
    assert r["dag_max_nodes"] == 16


def test_recommended_base_fallback():
    assert recommended_base({"max_concurrency": 6}) == 6
    assert recommended_base({}) == 2


def test_detect_hardware_shape():
    hw = detect_hardware()
    assert hw["cpu_count"] >= 1
    assert hw["memory_gb"] >= 0
    assert hw["platform"] != ""


def test_recommend_limits_requires_no_psutil():
    # 纯函数,不依赖 psutil 即可计算
    r = recommend_limits({"cpu_count": 4, "memory_gb": 8.0})
    assert r["max_concurrency"] == 2
    assert r["dag_max_nodes"] == 32  # cpu*8=32,8GB 内存档封顶 32


def test_recommend_limits_edge_memory_boundary():
    assert recommend_limits({"cpu_count": 8, "memory_gb": 7.9})["dag_max_nodes"] == 16
    assert recommend_limits({"cpu_count": 8, "memory_gb": 8.0})["dag_max_nodes"] == 32
    assert recommend_limits({"cpu_count": 8, "memory_gb": 15.9})["dag_max_nodes"] == 32
    assert recommend_limits({"cpu_count": 8, "memory_gb": 16.0})["dag_max_nodes"] == 64
    # 4 核机器: cpu*8=32,但 8GB 内存封顶 32 → 32
    assert recommend_limits({"cpu_count": 4, "memory_gb": 8.0})["dag_max_nodes"] == 32