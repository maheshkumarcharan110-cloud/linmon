"""Tests for the psutil-backed metric collector."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import psutil
import pytest

from linmon import collector
from linmon.collector import NetworkMetrics


def test_get_cpu_primes_counters_and_reads_sensors() -> None:
    """CPU readings are sampled twice and enriched with load and frequency."""

    def fake_cpu_percent(interval=None, percpu=False):
        return [10.0, 20.0] if percpu else 15.0

    with (
        patch.object(collector.psutil, "cpu_percent", side_effect=fake_cpu_percent),
        patch.object(collector.psutil, "cpu_count", side_effect=[2, 1]),
        patch.object(collector.psutil, "cpu_freq", return_value=SimpleNamespace(current=1999.6)),
        patch.object(collector.os, "getloadavg", return_value=(1, 2, 3)),
        patch.object(collector.time, "sleep") as sleep,
    ):
        cpu = collector.get_cpu(interval=0)

    assert cpu.percent == 15.0
    assert cpu.per_core == [10.0, 20.0]
    assert cpu.core_count == 2
    assert cpu.physical_core_count == 1
    assert cpu.load_avg == (1.0, 2.0, 3.0)
    assert cpu.frequency_mhz == 1999.6
    sleep.assert_called_once_with(0)


def test_get_cpu_handles_missing_sensors() -> None:
    """Missing frequency and load data degrade to safe defaults."""
    with (
        patch.object(
            collector.psutil,
            "cpu_percent",
            side_effect=lambda interval=None, percpu=False: [0.0] if percpu else 0.0,
        ),
        patch.object(collector.psutil, "cpu_count", return_value=1),
        patch.object(collector.psutil, "cpu_freq", return_value=None),
        patch.object(collector.os, "getloadavg", side_effect=OSError("unavailable")),
        patch.object(collector.time, "sleep"),
    ):
        cpu = collector.get_cpu()

    assert cpu.frequency_mhz is None
    assert cpu.load_avg == (0.0, 0.0, 0.0)


def test_get_memory_reads_counters() -> None:
    """Memory fields come from virtual_memory and swap_memory."""
    virtual = SimpleNamespace(percent=55.56, total=100, used=55, available=45)
    swap = SimpleNamespace(total=10, used=2, percent=20.0)
    with (
        patch.object(collector.psutil, "virtual_memory", return_value=virtual),
        patch.object(collector.psutil, "swap_memory", return_value=swap),
    ):
        memory = collector.get_memory()

    assert memory.percent == 55.6
    assert (memory.total, memory.used, memory.available) == (100, 55, 45)
    assert (memory.swap_total, memory.swap_used, memory.swap_percent) == (10, 2, 20.0)


def test_get_memory_without_virtual_stats_raises() -> None:
    """A host that cannot report physical memory fails explicitly."""
    with patch.object(collector.psutil, "virtual_memory", side_effect=OSError("denied")):
        with pytest.raises(RuntimeError, match="physical memory"):
            collector.get_memory()


def test_get_disks_skips_pseudo_and_unreadable_mounts() -> None:
    """Pseudo filesystems, duplicates and denied mounts are ignored."""
    partitions = [
        SimpleNamespace(device="/dev/sda1", mountpoint="/", fstype="ext4"),
        SimpleNamespace(device="proc", mountpoint="/proc", fstype="proc"),
        SimpleNamespace(device="/dev/sda2", mountpoint="/locked", fstype="ext4"),
        SimpleNamespace(device="/dev/sda1", mountpoint="/", fstype="ext4"),
    ]

    def fake_usage(mountpoint: str):
        if mountpoint == "/locked":
            raise OSError("permission denied")
        return SimpleNamespace(total=100, used=40, free=60, percent=40.0)

    with (
        patch.object(collector.psutil, "disk_partitions", return_value=partitions),
        patch.object(collector.psutil, "disk_usage", side_effect=fake_usage),
    ):
        disks = collector.get_disks()

    assert len(disks) == 1
    assert disks[0].mountpoint == "/"
    assert disks[0].percent == 40.0


def test_get_network_returns_zeroes_when_unavailable() -> None:
    """A missing net_io_counters result becomes an empty reading."""
    with patch.object(collector.psutil, "net_io_counters", return_value=None):
        network = collector.get_network()
    assert network.bytes_sent == 0
    assert network.bytes_recv == 0


def test_network_rates_compute_per_second_values() -> None:
    """Rates are deltas over elapsed time; cumulative totals are preserved."""
    previous = NetworkMetrics(bytes_sent=1000, bytes_recv=2000)
    current = NetworkMetrics(bytes_sent=3000, bytes_recv=6000)
    rated = collector.network_rates(previous, current, 2.0)

    assert rated.sent_per_sec == 1000.0
    assert rated.recv_per_sec == 2000.0
    assert (rated.bytes_sent, rated.bytes_recv) == (3000, 6000)


def test_network_rates_handle_bad_elapsed_and_counter_reset() -> None:
    """Zero elapsed time and counter resets never produce negative rates."""
    previous = NetworkMetrics(bytes_sent=100, bytes_recv=100)
    current = NetworkMetrics(bytes_sent=50, bytes_recv=50)
    assert collector.network_rates(previous, current, 0).sent_per_sec == 0.0
    assert collector.network_rates(previous, current, 1).sent_per_sec == 0.0
    assert collector.network_rates(previous, current, -1).recv_per_sec == 0.0


def test_get_uptime_is_never_negative() -> None:
    """A clock skew between boot time and now is clamped to zero."""
    with (
        patch.object(collector.time, "time", return_value=100.0),
        patch.object(collector.psutil, "boot_time", return_value=200.0),
    ):
        assert collector.get_uptime() == 0.0


def test_get_top_processes_sorts_and_limits() -> None:
    """Processes are ranked by both CPU and memory and trimmed to the limit."""

    class FakeProcess:
        def __init__(self, pid: int, name: str, cpus: list[float], mem: float, rss: int):
            self.info = {
                "pid": pid,
                "name": name,
                "memory_percent": mem,
                "memory_info": SimpleNamespace(rss=rss),
            }
            self._cpus = iter(cpus)

        def cpu_percent(self, interval=None) -> float:
            return next(self._cpus)

    processes = [
        FakeProcess(1, "a", [0, 10.0], 1.0, 100),
        FakeProcess(2, "b", [0, 50.0], 30.0, 300),
        FakeProcess(3, "c", [0, 5.0], 50.0, 500),
    ]
    with (
        patch.object(collector.psutil, "process_iter", return_value=processes),
        patch.object(collector.time, "sleep"),
    ):
        by_cpu, by_memory = collector.get_top_processes(limit=2)

    assert [process.pid for process in by_cpu] == [2, 1]
    assert [process.pid for process in by_memory] == [3, 2]
    assert by_cpu[0].cpu_percent == 50.0


def test_get_top_processes_skips_vanished_processes() -> None:
    """Processes that exit mid-sample do not break the collection."""

    class GoneProcess:
        info = {"pid": 9, "name": "gone", "memory_percent": 1.0, "memory_info": None}

        def cpu_percent(self, interval=None) -> float:
            raise psutil.NoSuchProcess(9)

    with (
        patch.object(collector.psutil, "process_iter", return_value=[GoneProcess()]),
        patch.object(collector.time, "sleep"),
    ):
        assert collector.get_top_processes(limit=5) == ([], [])


def test_collect_metrics_builds_serialisable_tree() -> None:
    """collect_metrics assembles all sections into a JSON-ready tree."""
    cpu = collector.CpuMetrics(1.0, [1.0], 1, 1, (0.0, 0.0, 0.0), None)
    memory = collector.MemoryMetrics(2.0, 100, 2, 98, 0, 0, 0.0)
    network = NetworkMetrics(5, 6)
    with (
        patch.object(collector, "get_cpu", return_value=cpu),
        patch.object(collector, "get_memory", return_value=memory),
        patch.object(collector, "get_disks", return_value=[]),
        patch.object(collector, "get_network", return_value=network),
        patch.object(collector, "get_uptime", return_value=12.0),
        patch.object(collector, "get_top_processes", return_value=([], [])) as top,
    ):
        metrics = collector.collect_metrics(top_n=3)

    assert metrics.cpu is cpu
    assert metrics.network is network
    top.assert_called_once_with(3, interval=0.2)
    payload = metrics.to_dict()
    assert payload["cpu"]["percent"] == 1.0
    assert json.loads(json.dumps(payload))["hostname"] == metrics.hostname
