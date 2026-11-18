"""Shared pytest fixtures for linmon tests."""

from __future__ import annotations

import pytest

from linmon.collector import (
    CpuMetrics,
    DiskMetrics,
    MemoryMetrics,
    NetworkMetrics,
    ProcessInfo,
    SystemMetrics,
)


@pytest.fixture
def sample_metrics() -> SystemMetrics:
    """Return a deterministic snapshot for tests that consume metrics."""
    return SystemMetrics(
        timestamp="2026-01-01T00:00:00+00:00",
        hostname="testhost",
        platform="Linux 6.0",
        uptime_seconds=90061.0,
        cpu=CpuMetrics(
            percent=42.5,
            per_core=[40.0, 45.0],
            core_count=2,
            physical_core_count=1,
            load_avg=(0.1, 0.2, 0.3),
            frequency_mhz=2400.0,
        ),
        memory=MemoryMetrics(
            percent=63.2,
            total=16 * 1024**3,
            used=10 * 1024**3,
            available=6 * 1024**3,
            swap_total=2 * 1024**3,
            swap_used=512 * 1024**2,
            swap_percent=25.0,
        ),
        disks=[
            DiskMetrics(
                device="/dev/sda1",
                mountpoint="/",
                fstype="ext4",
                total=100 * 1024**3,
                used=40 * 1024**3,
                free=60 * 1024**3,
                percent=40.0,
            )
        ],
        network=NetworkMetrics(bytes_sent=1000, bytes_recv=2000, packets_sent=10, packets_recv=20),
        top_by_cpu=[ProcessInfo(1, "init", 10.0, 1.0, 1024)],
        top_by_memory=[ProcessInfo(2, "app", 5.0, 20.0, 2048)],
    )
