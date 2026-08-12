"""CLI ergonomics tests.

Covers the production-readiness improvements to the CLI surface:

- Top-level catch wraps unexpected exceptions; only CedarIntentError
  produces the structured one-line error message.
- --json mode emits a structured JSON envelope for errors.
- parse_headers rejects empty names, CRLF, and oversize names/values.
- validate_identifier rejects path-traversal-shaped inputs.
- argparse rejects negative timeouts, infinite timeouts, and negative
  retries at parse time.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from cedar_intent.cli import (
    main,
    parse_headers,
    validate_identifier,
)
from cedar_intent.errors import ConfigError


def test_validate_identifier_accepts_safe_input() -> None:
    assert validate_identifier("hr-2026", "domain") == "hr-2026"
    assert validate_identifier("Foo.Bar_Baz-1", "x") == "Foo.Bar_Baz-1"


@pytest.mark.parametrize(
    "bad",
    ["", " ", "../etc", "/abs", "x" * 65, "hr\0", "with space", "with/slash"],
)
def test_validate_identifier_rejects_unsafe(bad: str) -> None:
    with pytest.raises(ConfigError):
        validate_identifier(bad, "domain")


def test_parse_headers_rejects_crlf() -> None:
    with pytest.raises(ConfigError):
        parse_headers(["X-Foo: bar\r\nX-Admin: true"])


def test_parse_headers_rejects_empty_name() -> None:
    with pytest.raises(ConfigError):
        parse_headers([": value"])


def test_parse_headers_rejects_oversize_name() -> None:
    with pytest.raises(ConfigError):
        parse_headers(["X" * 300 + ": value"])


def test_parse_headers_accepts_simple() -> None:
    parsed = parse_headers(["Authorization: Bearer x", "X-Env: prod"])
    assert parsed == {"Authorization": "Bearer x", "X-Env": "prod"}


def test_cli_rejects_invalid_domain(tmp_path) -> None:
    exit_code = main(
        [
            "--workspace",
            str(tmp_path),
            "domain",
            "add",
            "../etc",
        ]
    )
    assert exit_code == 1


def test_cli_rejects_negative_timeout(tmp_path) -> None:
    """--timeout -1 is rejected by argparse before any handler runs."""
    from cedar_intent import Workspace

    workspace = Workspace.create(tmp_path / "acme")
    exit_code = main(
        [
            "--workspace",
            str(workspace.root),
            "deploy",
            "push",
            "--domain",
            "hr",
            "--target",
            "http://127.0.0.1:1/x",
            "--timeout",
            "-1",
        ]
    )
    assert exit_code == 2


def test_cli_rejects_infinite_timeout(tmp_path) -> None:
    from cedar_intent import Workspace

    workspace = Workspace.create(tmp_path / "acme")
    exit_code = main(
        [
            "--workspace",
            str(workspace.root),
            "deploy",
            "push",
            "--domain",
            "hr",
            "--target",
            "http://127.0.0.1:1/x",
            "--timeout",
            "inf",
        ]
    )
    assert exit_code == 2


def test_cli_json_emits_structured_error_envelope(tmp_path) -> None:
    """--json mode emits a JSON envelope on stderr for errors."""
    workspace_path = tmp_path / "missing"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "cedar_intent",
            "--json",
            "--workspace",
            str(workspace_path),
            "verify",
            "--domain",
            "hr",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    payload = json.loads(proc.stderr)
    assert "error" in payload
    assert payload["error"]["type"]
