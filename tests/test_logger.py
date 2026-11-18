"""Tests for CSV and JSON logging."""

from __future__ import annotations

import csv
import json

import pytest

from linmon.logger import LOG_FIELDS, MetricLogger, metrics_to_row


def test_metrics_to_row_flattens_snapshot(sample_metrics) -> None:
    """The log row contains exactly the declared columns."""
    row = metrics_to_row(sample_metrics)
    assert tuple(row) == LOG_FIELDS
    assert row["cpu_percent"] == 42.5
    assert row["memory_percent"] == 63.2
    assert row["disk_percent"] == 40.0
    assert row["net_bytes_recv"] == 2000


def test_csv_creates_header_once_and_appends(sample_metrics, tmp_path) -> None:
    """Repeated writes add rows without repeating the header."""
    path = tmp_path / "nested" / "readings.csv"
    logger = MetricLogger(path)

    logger.log(sample_metrics)
    logger.log(sample_metrics)

    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert rows[0]["hostname"] == "testhost"
    assert path.read_text(encoding="utf-8").count("timestamp") == 1


def test_json_creates_valid_array_and_appends(sample_metrics, tmp_path) -> None:
    """JSON logs stay valid arrays across multiple appends."""
    path = tmp_path / "readings.json"
    logger = MetricLogger(path)

    logger.log(sample_metrics)
    logger.log(sample_metrics)

    readings = json.loads(path.read_text(encoding="utf-8"))
    assert len(readings) == 2
    assert readings[1]["cpu_percent"] == 42.5
    assert not (tmp_path / "readings.json.tmp").exists()


def test_unsupported_suffix_is_rejected(tmp_path) -> None:
    """Only .csv and .json log targets are accepted."""
    with pytest.raises(ValueError, match="Unsupported log file type"):
        MetricLogger(tmp_path / "readings.txt")


def test_corrupt_json_is_not_overwritten(sample_metrics, tmp_path) -> None:
    """Appending to malformed JSON fails instead of destroying readings."""
    path = tmp_path / "readings.json"
    path.write_text("this is not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        MetricLogger(path).log(sample_metrics)
    assert path.read_text(encoding="utf-8") == "this is not json"
