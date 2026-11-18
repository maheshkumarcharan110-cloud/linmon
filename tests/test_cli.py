"""Tests for argument parsing and CLI orchestration."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from linmon import cli


def test_parser_rejects_invalid_values() -> None:
    """Out-of-range numbers fail with a usage error."""
    parser = cli.build_parser()
    for argv in (["--interval", "0"], ["--top", "-2"], ["--alert-cpu", "101"]):
        with pytest.raises(SystemExit) as error:
            parser.parse_args(argv)
        assert error.value.code == 2


def test_json_mode_emits_only_json(sample_metrics, capsys) -> None:
    """--json writes a parseable object and nothing else to stdout."""
    with patch.object(cli, "collect_metrics", return_value=sample_metrics):
        assert cli.main(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["hostname"] == "testhost"


def test_json_and_live_are_mutually_exclusive() -> None:
    """Combining --json with --live fails fast."""
    with pytest.raises(SystemExit):
        cli.main(["--json", "--live"])


def test_bad_log_suffix_is_a_usage_error(tmp_path) -> None:
    """An unsupported log extension is reported as a usage error."""
    with pytest.raises(SystemExit):
        cli.main(["--log", str(tmp_path / "readings.txt")])


def test_collection_failure_returns_error_code(capsys) -> None:
    """A psutil failure produces a message and exit code 1, not a traceback."""
    with patch.object(cli, "collect_metrics", side_effect=OSError("denied")):
        assert cli.main([]) == 1
    assert "could not collect metrics" in capsys.readouterr().err
