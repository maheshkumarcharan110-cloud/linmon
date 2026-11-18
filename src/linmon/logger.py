"""Append system snapshots to CSV or JSON log files."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .collector import SystemMetrics

LOG_FIELDS: tuple[str, ...] = (
    "timestamp",
    "hostname",
    "uptime_seconds",
    "cpu_percent",
    "memory_percent",
    "disk_percent",
    "net_bytes_sent",
    "net_bytes_recv",
)


def metrics_to_row(metrics: SystemMetrics) -> dict[str, Any]:
    """Flatten a snapshot into the fixed set of columns used by log files."""
    return {
        "timestamp": metrics.timestamp,
        "hostname": metrics.hostname,
        "uptime_seconds": round(metrics.uptime_seconds, 1),
        "cpu_percent": round(metrics.cpu.percent, 1),
        "memory_percent": round(metrics.memory.percent, 1),
        "disk_percent": round(metrics.disk_percent, 1),
        "net_bytes_sent": metrics.network.bytes_sent,
        "net_bytes_recv": metrics.network.bytes_recv,
    }


class MetricLogger:
    """Append readings to a ``.csv`` or ``.json`` file.

    CSV files get a header on first use. JSON files are kept as a valid array
    of objects and written through a temporary file so an interrupted write
    cannot corrupt existing readings.
    """

    SUPPORTED_SUFFIXES = frozenset({".csv", ".json"})

    def __init__(self, path: str | Path) -> None:
        """Validate and store the destination path."""
        target = Path(path).expanduser()
        if target.suffix.lower() not in self.SUPPORTED_SUFFIXES:
            suffixes = ", ".join(sorted(self.SUPPORTED_SUFFIXES))
            raise ValueError(f"Unsupported log file type {target.suffix!r}; use {suffixes}")
        self.path = target

    def log(self, metrics: SystemMetrics) -> None:
        """Append one reading to the configured file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = metrics_to_row(metrics)
        if self.path.suffix.lower() == ".csv":
            self._append_csv(row)
        else:
            self._append_json(row)

    def _append_csv(self, row: dict[str, Any]) -> None:
        needs_header = not self.path.exists() or self.path.stat().st_size == 0
        with self.path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS)
            if needs_header:
                writer.writeheader()
            writer.writerow(row)

    def _append_json(self, row: dict[str, Any]) -> None:
        readings: list[dict[str, Any]] = []
        if self.path.exists() and self.path.stat().st_size:
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"Cannot append to {self.path}: not valid JSON") from exc
            if not isinstance(loaded, list):
                raise ValueError(f"Cannot append to {self.path}: expected a JSON array")
            readings = loaded

        readings.append(row)
        temporary = Path(f"{self.path}.tmp")
        temporary.write_text(json.dumps(readings, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)
