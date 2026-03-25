"""Tests for --json-errors global flag behavior."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from treeloom.cli.main import main


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    """Run main() and return (returncode, stdout, stderr)."""
    rc = main(argv)
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


class TestJsonErrors:
    def test_file_not_found_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        """--json-errors produces a JSON object for FileNotFoundError."""
        def raise_fnf(args, cfg):  # noqa: ANN001
            raise FileNotFoundError(2, "No such file or directory", "missing.json")

        with patch("treeloom.cli.build.run_build", side_effect=raise_fnf):
            rc, _, err = _run(["--json-errors", "build", "missing.json"], capsys)

        assert rc == 1
        obj = json.loads(err.strip())
        assert obj["error"] == "file_not_found"
        assert "message" in obj
        assert obj["path"] == "missing.json"

    def test_file_not_found_plain(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Without --json-errors, FileNotFoundError produces plain text on stderr."""
        def raise_fnf(args, cfg):  # noqa: ANN001
            raise FileNotFoundError(2, "No such file or directory", "missing.json")

        with patch("treeloom.cli.build.run_build", side_effect=raise_fnf):
            rc, _, err = _run(["build", "missing.json"], capsys)

        assert rc == 1
        assert err.startswith("Error:")
        # Must not be JSON
        with pytest.raises(json.JSONDecodeError):
            json.loads(err.strip())

    def test_json_decode_error_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        """--json-errors produces a JSON object for json.JSONDecodeError."""
        import json as _json

        def raise_json(args, cfg):  # noqa: ANN001
            raise _json.JSONDecodeError("Expecting value", "", 0)

        with patch("treeloom.cli.info.run_info", side_effect=raise_json):
            rc, _, err = _run(["--json-errors", "info", "some.json"], capsys)

        assert rc == 1
        obj = json.loads(err.strip())
        assert obj["error"] == "invalid_json"
        assert "message" in obj

    def test_json_decode_error_plain(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Without --json-errors, json.JSONDecodeError produces plain text."""
        import json as _json

        def raise_json(args, cfg):  # noqa: ANN001
            raise _json.JSONDecodeError("Expecting value", "", 0)

        with patch("treeloom.cli.info.run_info", side_effect=raise_json):
            rc, _, err = _run(["info", "some.json"], capsys)

        assert rc == 1
        assert "invalid JSON" in err

    def test_unexpected_error_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        """--json-errors produces a JSON object for unexpected exceptions."""
        def raise_unexpected(args, cfg):  # noqa: ANN001
            raise RuntimeError("something went wrong")

        with patch("treeloom.cli.build.run_build", side_effect=raise_unexpected):
            rc, _, err = _run(["--json-errors", "build", "input.py"], capsys)

        assert rc == 1
        obj = json.loads(err.strip())
        assert obj["error"] == "unexpected_error"
        assert obj["message"] == "something went wrong"
        assert obj["type"] == "RuntimeError"

    def test_unexpected_error_plain(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Without --json-errors, unexpected exceptions produce plain text."""
        def raise_unexpected(args, cfg):  # noqa: ANN001
            raise RuntimeError("something went wrong")

        with patch("treeloom.cli.build.run_build", side_effect=raise_unexpected):
            rc, _, err = _run(["build", "input.py"], capsys)

        assert rc == 1
        assert "something went wrong" in err
        with pytest.raises(json.JSONDecodeError):
            json.loads(err.strip())
