"""Threshold checks and desktop notifications for linmon."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass

from rich.console import Console

from .collector import SystemMetrics


@dataclass(frozen=True, slots=True)
class Alert:
    """A single threshold breach."""

    kind: str
    message: str
    value: float
    threshold: float


def evaluate(
    metrics: SystemMetrics,
    cpu_threshold: float | None = None,
    ram_threshold: float | None = None,
) -> list[Alert]:
    """Return alerts for any threshold that has been reached or exceeded."""
    alerts: list[Alert] = []

    if cpu_threshold is not None and metrics.cpu.percent >= cpu_threshold:
        alerts.append(
            Alert(
                kind="cpu",
                message=(f"CPU usage is {metrics.cpu.percent:.1f}% (threshold {cpu_threshold:g}%)"),
                value=metrics.cpu.percent,
                threshold=cpu_threshold,
            )
        )

    if ram_threshold is not None and metrics.memory.percent >= ram_threshold:
        alerts.append(
            Alert(
                kind="ram",
                message=(
                    f"RAM usage is {metrics.memory.percent:.1f}% (threshold {ram_threshold:g}%)"
                ),
                value=metrics.memory.percent,
                threshold=ram_threshold,
            )
        )

    return alerts


def notify(message: str, *, timeout: float = 5.0) -> bool:
    """Send a desktop notification via ``notify-send`` when it is available.

    Returns ``True`` only when a notification was actually delivered. Missing
    binaries, D-Bus problems and timeouts are all handled silently.
    """
    binary = shutil.which("notify-send")
    if binary is None:
        return False
    try:
        result = subprocess.run(
            [binary, "--urgency=critical", "linmon", message],
            check=False,
            capture_output=True,
            timeout=max(0.1, timeout),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


class AlertManager:
    """Print and notify about new alerts without repeating active ones.

    An alert is re-announced only after its condition has cleared, which keeps
    live mode from spamming the terminal and the notification daemon.
    """

    def __init__(self, console: Console, *, desktop: bool = True) -> None:
        """Create a manager that prints to *console* and optionally notifies."""
        self._console = console
        self._desktop = desktop
        self._active: set[tuple[str, float]] = set()

    def process(self, alerts: Iterable[Alert]) -> None:
        """Announce alerts that were not already active on the previous call."""
        current = {(alert.kind, alert.threshold) for alert in alerts}
        for alert in alerts:
            key = (alert.kind, alert.threshold)
            if key in self._active:
                continue
            self._console.print(f"[bold red]ALERT[/] {alert.message}")
            if self._desktop and notify(alert.message):
                self._console.print("[dim]Desktop notification sent.[/]")
        self._active = current
