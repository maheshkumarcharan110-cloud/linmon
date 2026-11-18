"""Argument parsing and entry point for the ``linmon`` command."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence

import psutil
from rich.console import Console
from rich.live import Live

from . import __version__
from .alerts import AlertManager, evaluate
from .collector import NetworkMetrics, collect_metrics
from .display import build_dashboard, build_snapshot_panel, build_top_panel
from .logger import MetricLogger


def _percentage(value: str) -> float:
    """Parse a 0-100 percentage for argparse."""
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{value!r} is not a number") from exc
    if not 0.0 <= number <= 100.0:
        raise argparse.ArgumentTypeError("must be between 0 and 100")
    return number


def _positive_float(value: str) -> float:
    """Parse a strictly positive float for argparse."""
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{value!r} is not a number") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def _positive_int(value: str) -> int:
    """Parse a strictly positive integer for argparse."""
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{value!r} is not an integer") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def build_parser() -> argparse.ArgumentParser:
    """Create the fully configured argument parser."""
    parser = argparse.ArgumentParser(
        prog="linmon",
        description=(
            "linmon is a command-line system monitor for Linux. By default it "
            "prints one snapshot of CPU, RAM, disk, network and uptime."
        ),
        epilog=(
            "examples:\n"
            "  linmon                                  one-time snapshot\n"
            "  linmon --live --interval 1 --top 8       live dashboard with processes\n"
            "  linmon --json > snapshot.json           machine-readable snapshot\n"
            "  linmon --log readings.csv --alert-cpu 90 --alert-ram 85\n"
            "\nUse Ctrl+C to leave live mode cleanly."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="run a live-updating dashboard instead of printing one snapshot",
    )
    parser.add_argument(
        "--interval",
        type=_positive_float,
        default=2.0,
        metavar="SECONDS",
        help="refresh interval for --live (default: 2)",
    )
    parser.add_argument(
        "--top",
        type=_positive_int,
        default=0,
        metavar="N",
        help="show the top N processes by CPU and by memory",
    )
    parser.add_argument(
        "--log",
        metavar="FILE",
        help="append each reading to FILE (.csv or .json), creating it if needed",
    )
    parser.add_argument(
        "--alert-cpu",
        type=_percentage,
        metavar="PCT",
        help="warn when CPU usage reaches PCT percent (0-100)",
    )
    parser.add_argument(
        "--alert-ram",
        type=_percentage,
        metavar="PCT",
        help="warn when RAM usage reaches PCT percent (0-100)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the snapshot as JSON to stdout (for scripts and pipelines)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"linmon {__version__}",
        help="show the program version and exit",
    )
    return parser


def _run_once(
    args: argparse.Namespace,
    console: Console,
    status: Console,
    alert_manager: AlertManager,
    logger: MetricLogger | None,
) -> int:
    """Collect and report a single snapshot."""
    metrics = collect_metrics(top_n=args.top, cpu_interval=0.2)

    if args.json:
        sys.stdout.write(json.dumps(metrics.to_dict(), indent=2, sort_keys=True) + "\n")
    else:
        console.print(build_snapshot_panel(metrics))
        if args.top:
            console.print(build_top_panel(metrics, args.top))

    if logger is not None:
        logger.log(metrics)
        status.print(f"[dim]Appended reading to {logger.path}[/]")

    alert_manager.process(evaluate(metrics, args.alert_cpu, args.alert_ram))
    return 0


def _run_live(
    args: argparse.Namespace,
    console: Console,
    alert_manager: AlertManager,
    logger: MetricLogger | None,
) -> int:
    """Run the live dashboard until interrupted."""
    interval = args.interval
    previous: NetworkMetrics | None = None
    last_sample = time.monotonic()

    with Live(console=console, refresh_per_second=4, screen=True, transient=False) as live:
        while True:
            started = time.monotonic()
            elapsed = started - last_sample if previous is not None else 0.0
            last_sample = started

            metrics = collect_metrics(
                top_n=args.top,
                cpu_interval=min(0.2, max(0.01, interval / 4)),
                previous_network=previous,
                elapsed=elapsed,
            )
            previous = metrics.network

            live.update(build_dashboard(metrics, args.top, interval))
            if logger is not None:
                logger.log(metrics)
            alert_manager.process(evaluate(metrics, args.alert_cpu, args.alert_ram))

            remaining = interval - (time.monotonic() - started)
            if remaining > 0:
                time.sleep(remaining)


def main(argv: Sequence[str] | None = None) -> int:
    """Run linmon and return a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    console = Console()
    status = Console(stderr=True)

    if args.json and args.live:
        parser.error("--json and --live cannot be used together")

    logger: MetricLogger | None = None
    if args.log:
        try:
            logger = MetricLogger(args.log)
        except ValueError as exc:
            parser.error(str(exc))

    alert_console = status if args.json else console
    alert_manager = AlertManager(alert_console)

    try:
        if args.live:
            return _run_live(args, console, alert_manager, logger)
        return _run_once(args, console, status, alert_manager, logger)
    except KeyboardInterrupt:
        status.print("\n[yellow]Interrupted - exiting linmon.[/]")
        return 0
    except (psutil.Error, OSError, RuntimeError) as exc:
        status.print(f"[red]linmon could not collect metrics: {exc}[/]")
        return 1
