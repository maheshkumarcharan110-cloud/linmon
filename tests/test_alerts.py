"""Tests for threshold evaluation and notifications."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from unittest.mock import patch

from linmon import alerts
from linmon.alerts import AlertManager, evaluate, notify


def test_evaluate_reports_reached_thresholds(sample_metrics) -> None:
    """CPU and RAM alerts fire at or above their thresholds."""
    found = evaluate(sample_metrics, 40.0, 60.0)
    assert [alert.kind for alert in found] == ["cpu", "ram"]
    assert "42.5%" in found[0].message
    assert found[0].value == 42.5
    assert found[1].threshold == 60.0


def test_evaluate_ignores_unset_and_unreached_thresholds(sample_metrics) -> None:
    """No alerts are produced without thresholds or below them."""
    assert evaluate(sample_metrics) == []
    assert evaluate(sample_metrics, 90, 90) == []
    assert [item.kind for item in evaluate(sample_metrics, 42.5)] == ["cpu"]


def test_alert_manager_announces_only_new_alerts(sample_metrics) -> None:
    """An active alert is not repeated until its condition clears."""
    printed: list[str] = []
    console = SimpleNamespace(print=lambda message, *a, **k: printed.append(message))
    manager = AlertManager(console, desktop=False)
    active = evaluate(sample_metrics, 40, 60)

    manager.process(active)
    manager.process(active)
    assert len(printed) == 2

    manager.process([])
    manager.process(active)
    assert len(printed) == 4


def test_notify_without_binary_is_noop() -> None:
    """Missing notify-send is handled silently."""
    with patch.object(alerts.shutil, "which", return_value=None):
        assert notify("hello") is False


def test_notify_success() -> None:
    """A successful notification is reported and includes the message."""
    with (
        patch.object(alerts.shutil, "which", return_value="/usr/bin/notify-send"),
        patch.object(
            alerts.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0),
        ) as run,
    ):
        assert notify("hello") is True
    assert run.call_args.args[0][-1] == "hello"


def test_notify_handles_subprocess_failures() -> None:
    """Timeouts and failing commands do not raise."""
    with (
        patch.object(alerts.shutil, "which", return_value="/usr/bin/notify-send"),
        patch.object(
            alerts.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired("notify-send", 5),
        ),
    ):
        assert notify("hello") is False
