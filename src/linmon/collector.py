"""Collect Linux system metrics using :mod:`psutil`.

This is the only module that talks to psutil directly. Every public getter is
defensive: a single unreadable disk, missing sensor, or vanished process is
skipped rather than aborting the whole snapshot. That keeps ``linmon`` useful
inside containers and on hardened hosts where some counters are restricted.
"""

from __future__ import annotations

import os
import platform
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone

import psutil

from . import __version__

# Filesystem types that do not represent real, mountable storage.
_PSEUDO_FSTYPES = frozenset(
    {
        "autofs",
        "binfmt_misc",
        "cgroup",
        "cgroup2",
        "configfs",
        "debugfs",
        "devpts",
        "devtmpfs",
        "efivarfs",
        "fusectl",
        "fuse.gvfsd-fuse",
        "hugetlbfs",
        "mqueue",
        "proc",
        "pstore",
        "ramfs",
        "securityfs",
        "squashfs",
        "sysfs",
        "tmpfs",
        "tracefs",
    }
)


@dataclass(frozen=True, slots=True)
class CpuMetrics:
    """CPU utilisation, load average and clock speed."""

    percent: float
    per_core: list[float]
    core_count: int
    physical_core_count: int | None
    load_avg: tuple[float, float, float]
    frequency_mhz: float | None


@dataclass(frozen=True, slots=True)
class MemoryMetrics:
    """Physical and swap memory usage, in bytes and percentages."""

    percent: float
    total: int
    used: int
    available: int
    swap_total: int
    swap_used: int
    swap_percent: float


@dataclass(frozen=True, slots=True)
class DiskMetrics:
    """Usage of one mounted filesystem."""

    device: str
    mountpoint: str
    fstype: str
    total: int
    used: int
    free: int
    percent: float


@dataclass(frozen=True, slots=True)
class NetworkMetrics:
    """Cumulative network counters plus optional per-second rates."""

    bytes_sent: int
    bytes_recv: int
    packets_sent: int = 0
    packets_recv: int = 0
    sent_per_sec: float = 0.0
    recv_per_sec: float = 0.0


@dataclass(frozen=True, slots=True)
class ProcessInfo:
    """A single process as reported by the top-process sampler."""

    pid: int
    name: str
    cpu_percent: float
    memory_percent: float
    memory_rss: int


@dataclass(frozen=True, slots=True)
class SystemMetrics:
    """A complete, JSON-serialisable snapshot of the machine."""

    timestamp: str
    hostname: str
    platform: str
    uptime_seconds: float
    cpu: CpuMetrics
    memory: MemoryMetrics
    disks: list[DiskMetrics]
    network: NetworkMetrics
    top_by_cpu: list[ProcessInfo] = field(default_factory=list)
    top_by_memory: list[ProcessInfo] = field(default_factory=list)

    @property
    def disk_percent(self) -> float:
        """Return the usage percentage of the fullest mounted filesystem."""
        return max((disk.percent for disk in self.disks), default=0.0)

    def to_dict(self) -> dict[str, object]:
        """Return a plain dictionary suitable for ``json.dumps``."""
        return {
            "tool_version": __version__,
            "timestamp": self.timestamp,
            "hostname": self.hostname,
            "platform": self.platform,
            "uptime_seconds": round(self.uptime_seconds, 1),
            "disk_percent": round(self.disk_percent, 1),
            "cpu": asdict(self.cpu),
            "memory": asdict(self.memory),
            "disks": [asdict(disk) for disk in self.disks],
            "network": asdict(self.network),
            "top_by_cpu": [asdict(proc) for proc in self.top_by_cpu],
            "top_by_memory": [asdict(proc) for proc in self.top_by_memory],
        }


def get_cpu(interval: float = 0.2) -> CpuMetrics:
    """Sample CPU usage, per-core usage, load average and clock frequency.

    psutil's first percentage reading after import has no baseline and is
    meaningless, so both counters are primed before the real reading is taken.
    A single short sleep covers both samples.
    """
    psutil.cpu_percent(interval=None)
    psutil.cpu_percent(interval=None, percpu=True)
    time.sleep(max(0.0, interval))

    percent = float(psutil.cpu_percent(interval=None))
    per_core = [float(value) for value in psutil.cpu_percent(interval=None, percpu=True)]

    try:
        frequency = psutil.cpu_freq()
    except (OSError, psutil.Error):
        frequency = None
    frequency_mhz = round(float(frequency.current), 1) if frequency is not None else None

    try:
        one, five, fifteen = os.getloadavg()
        load_avg = (float(one), float(five), float(fifteen))
    except (OSError, ValueError):
        load_avg = (0.0, 0.0, 0.0)

    return CpuMetrics(
        percent=round(percent, 1),
        per_core=[round(value, 1) for value in per_core],
        core_count=psutil.cpu_count(logical=True) or len(per_core) or 1,
        physical_core_count=psutil.cpu_count(logical=False),
        load_avg=load_avg,
        frequency_mhz=frequency_mhz,
    )


def get_memory() -> MemoryMetrics:
    """Return physical and swap memory usage."""
    try:
        virtual = psutil.virtual_memory()
    except (OSError, psutil.Error):
        virtual = None
    try:
        swap = psutil.swap_memory()
    except (OSError, psutil.Error):
        swap = None

    if virtual is None:
        raise RuntimeError("Unable to read physical memory statistics")

    return MemoryMetrics(
        percent=round(float(virtual.percent), 1),
        total=int(virtual.total),
        used=int(virtual.used),
        available=int(virtual.available),
        swap_total=int(swap.total) if swap is not None else 0,
        swap_used=int(swap.used) if swap is not None else 0,
        swap_percent=round(float(swap.percent), 1) if swap is not None else 0.0,
    )


def get_disks() -> list[DiskMetrics]:
    """Return usage for each real mounted filesystem, skipping unreadable ones."""
    disks: list[DiskMetrics] = []
    seen: set[tuple[str, str]] = set()

    try:
        partitions = psutil.disk_partitions(all=False)
    except (OSError, psutil.Error):
        return disks

    for partition in partitions:
        if partition.fstype in _PSEUDO_FSTYPES:
            continue
        key = (partition.device, partition.mountpoint)
        if key in seen:
            continue
        seen.add(key)
        try:
            usage = psutil.disk_usage(partition.mountpoint)
        except (OSError, psutil.Error):
            continue
        if usage.total <= 0:
            continue
        disks.append(
            DiskMetrics(
                device=partition.device,
                mountpoint=partition.mountpoint,
                fstype=partition.fstype,
                total=int(usage.total),
                used=int(usage.used),
                free=int(usage.free),
                percent=round(float(usage.percent), 1),
            )
        )
    return disks


def get_network() -> NetworkMetrics:
    """Return cumulative network I/O counters, or zeroes if unavailable."""
    try:
        counters = psutil.net_io_counters()
    except (OSError, psutil.Error):
        counters = None
    if counters is None:
        return NetworkMetrics(bytes_sent=0, bytes_recv=0)

    return NetworkMetrics(
        bytes_sent=int(counters.bytes_sent),
        bytes_recv=int(counters.bytes_recv),
        packets_sent=int(counters.packets_sent),
        packets_recv=int(counters.packets_recv),
    )


def network_rates(
    previous: NetworkMetrics, current: NetworkMetrics, elapsed: float
) -> NetworkMetrics:
    """Return *current* with per-second rates derived from *previous*.

    Negative deltas (which happen after an interface reset) are clamped to
    zero. If *elapsed* is not positive the rates stay at their default zero.
    """
    if elapsed <= 0:
        return current
    return replace(
        current,
        sent_per_sec=round(max(0.0, current.bytes_sent - previous.bytes_sent) / elapsed, 1),
        recv_per_sec=round(max(0.0, current.bytes_recv - previous.bytes_recv) / elapsed, 1),
    )


def get_uptime() -> float:
    """Return seconds since boot, never negative."""
    try:
        return max(0.0, float(time.time() - psutil.boot_time()))
    except (OSError, psutil.Error):
        return 0.0


def get_top_processes(
    limit: int = 5, interval: float = 0.1
) -> tuple[list[ProcessInfo], list[ProcessInfo]]:
    """Return the top *limit* processes by CPU and by memory.

    Per-process CPU percentages need two samples, so counters are primed, a
    short wait follows, and then the real values are read. Processes that exit
    or deny access during that window are simply skipped.
    """
    if limit <= 0:
        return [], []

    try:
        processes = list(
            psutil.process_iter(attrs=["pid", "name", "memory_percent", "memory_info"])
        )
    except (OSError, psutil.Error):
        return [], []

    for process in processes:
        try:
            process.cpu_percent(interval=None)
        except (OSError, psutil.Error):
            continue

    time.sleep(max(0.0, interval))

    collected: list[ProcessInfo] = []
    for process in processes:
        try:
            info = process.info
            memory_info = info.get("memory_info")
            collected.append(
                ProcessInfo(
                    pid=int(info.get("pid") or 0),
                    name=str(info.get("name") or "unknown"),
                    cpu_percent=round(float(process.cpu_percent(interval=None)), 1),
                    memory_percent=round(float(info.get("memory_percent") or 0.0), 1),
                    memory_rss=int(getattr(memory_info, "rss", 0) or 0),
                )
            )
        except (OSError, psutil.Error, TypeError, ValueError):
            continue

    by_cpu = sorted(collected, key=lambda item: item.cpu_percent, reverse=True)[:limit]
    by_memory = sorted(collected, key=lambda item: item.memory_percent, reverse=True)[:limit]
    return by_cpu, by_memory


def collect_metrics(
    top_n: int = 0,
    cpu_interval: float = 0.2,
    *,
    previous_network: NetworkMetrics | None = None,
    elapsed: float = 0.0,
) -> SystemMetrics:
    """Build a full snapshot.

    ``previous_network`` and ``elapsed`` are used by live mode to turn raw
    counters into per-second rates without sampling the network twice.
    """
    network = get_network()
    if previous_network is not None:
        network = network_rates(previous_network, network, elapsed)

    top_cpu, top_memory = ([], [])
    if top_n > 0:
        top_cpu, top_memory = get_top_processes(top_n, interval=min(cpu_interval, 0.2))

    return SystemMetrics(
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        hostname=platform.node(),
        platform=f"{platform.system()} {platform.release()}".strip(),
        uptime_seconds=get_uptime(),
        cpu=get_cpu(interval=cpu_interval),
        memory=get_memory(),
        disks=get_disks(),
        network=network,
        top_by_cpu=top_cpu,
        top_by_memory=top_memory,
    )
