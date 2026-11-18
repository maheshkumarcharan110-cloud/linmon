"""Rich-based terminal rendering for linmon snapshots and live dashboards."""

from __future__ import annotations

from rich.columns import Columns
from rich.console import Group
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.table import Table
from rich.text import Text

from .collector import ProcessInfo, SystemMetrics


def format_bytes(value: float) -> str:
    """Format a byte count using binary (1024-based) units."""
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(size) < 1024.0 or unit == "TiB":
            if unit == "B":
                return f"{size:.0f} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TiB"


def format_uptime(seconds: float) -> str:
    """Format an uptime in seconds as a compact human-readable string."""
    total = max(0, int(seconds))
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)
    if days:
        return f"{days}d {hours:02d}h {minutes:02d}m"
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    return f"{minutes}m {secs:02d}s"


def _usage_bar(percent: float, color: str = "cyan") -> ProgressBar:
    """Build a fixed-width progress bar for a 0-100 percentage."""
    value = max(0.0, min(100.0, float(percent)))
    return ProgressBar(
        total=100,
        completed=value,
        width=24,
        complete_style=color,
        finished_style=color,
    )


def _color_for(percent: float) -> str:
    """Pick a warning colour based on a usage percentage."""
    if percent >= 90:
        return "red"
    if percent >= 75:
        return "yellow"
    return "cyan"


def _process_table(title: str, processes: list[ProcessInfo], color: str) -> Table:
    """Build a table for one list of top processes."""
    table = Table(title=title, header_style=f"bold {color}", expand=True)
    table.add_column("PID", justify="right", style="dim", width=7)
    table.add_column("Process", overflow="ellipsis", ratio=2)
    table.add_column("CPU%", justify="right", width=7)
    table.add_column("MEM%", justify="right", width=7)
    table.add_column("RSS", justify="right", width=10)
    if not processes:
        table.add_row("-", "no processes available", "-", "-", "-")
        return table
    for process in processes:
        table.add_row(
            str(process.pid),
            process.name,
            f"{process.cpu_percent:.1f}",
            f"{process.memory_percent:.1f}",
            format_bytes(process.memory_rss),
        )
    return table


def build_snapshot_panel(metrics: SystemMetrics) -> Panel:
    """Build a rich panel showing the core one-time snapshot."""
    table = Table(box=None, show_header=False, pad_edge=False, padding=(0, 1))
    table.add_column("Metric", style="bold cyan", width=9)
    table.add_column("Usage", width=26)
    table.add_column("Detail", style="dim")

    table.add_row("Host", Text(""), f"{metrics.hostname}  {metrics.platform}")
    table.add_row("Uptime", Text(""), format_uptime(metrics.uptime_seconds))

    cpu = metrics.cpu
    load = "/".join(f"{value:.2f}" for value in cpu.load_avg)
    cpu_detail = f"{cpu.percent:5.1f}%  {cpu.core_count} cores  load {load}"
    if cpu.frequency_mhz is not None:
        cpu_detail += f"  {cpu.frequency_mhz:.0f} MHz"
    table.add_row("CPU", _usage_bar(cpu.percent, _color_for(cpu.percent)), cpu_detail)

    memory = metrics.memory
    table.add_row(
        "Memory",
        _usage_bar(memory.percent, _color_for(memory.percent)),
        f"{memory.percent:5.1f}%  {format_bytes(memory.used)}/{format_bytes(memory.total)}",
    )
    if memory.swap_total > 0:
        table.add_row(
            "Swap",
            _usage_bar(memory.swap_percent, "magenta"),
            (
                f"{memory.swap_percent:5.1f}%  "
                f"{format_bytes(memory.swap_used)}/{format_bytes(memory.swap_total)}"
            ),
        )

    # A machine can expose dozens of mounts; show the most useful few.
    visible_disks = metrics.disks[:6]
    for index, disk in enumerate(visible_disks, start=1):
        label = "Disk" if len(metrics.disks) == 1 else f"Disk {index}"
        table.add_row(
            label,
            _usage_bar(disk.percent, _color_for(disk.percent)),
            (
                f"{disk.percent:5.1f}%  {format_bytes(disk.used)}/"
                f"{format_bytes(disk.total)}  {disk.mountpoint} ({disk.fstype})"
            ),
        )
    if len(metrics.disks) > len(visible_disks):
        extra = len(metrics.disks) - len(visible_disks)
        table.add_row("", Text(""), f"[dim]+{extra} more mounts[/]")
    if not metrics.disks:
        table.add_row("Disk", Text(""), "[dim]no mounted filesystems available[/]")

    network = metrics.network
    if network.sent_per_sec or network.recv_per_sec:
        network_detail = (
            f"down {format_bytes(network.recv_per_sec)}/s  "
            f"up {format_bytes(network.sent_per_sec)}/s  "
            f"(total down {format_bytes(network.bytes_recv)}, "
            f"up {format_bytes(network.bytes_sent)})"
        )
    else:
        network_detail = (
            f"down {format_bytes(network.bytes_recv)}  "
            f"up {format_bytes(network.bytes_sent)}  (cumulative)"
        )
    table.add_row("Network", Text(""), network_detail)

    return Panel(table, title=f"linmon snapshot - {metrics.timestamp}", border_style="cyan")


def build_top_panel(metrics: SystemMetrics, limit: int) -> Columns:
    """Build the side-by-side CPU and memory process tables."""
    del limit  # The collector already applied the limit; kept for a clear API.
    return Columns(
        [
            _process_table("Top by CPU", metrics.top_by_cpu, "red"),
            _process_table("Top by memory", metrics.top_by_memory, "cyan"),
        ],
        equal=True,
        expand=True,
    )


def build_dashboard(metrics: SystemMetrics, top_n: int, interval: float) -> Group:
    """Build the full live display, including optional process tables."""
    parts: list[object] = [build_snapshot_panel(metrics)]
    if top_n > 0:
        parts.append(build_top_panel(metrics, top_n))
    parts.append(Text(f"Refreshing every {interval:g}s  |  Ctrl+C to quit", style="dim"))
    return Group(*parts)
