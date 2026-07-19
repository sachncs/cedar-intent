"""Tests for the verify and deploy CLI subcommands."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from cedar_intent import cli
from cedar_intent.cli import (
    main,
    parse_headers,
)


def make_workspace(tmp_path: Path) -> Path:
    schema = {
        "PhotoFlash": {
            "entityTypes": {"User": {}, "Photo": {}},
            "actions": {
                "viewPhoto": {
                    "appliesTo": {
                        "principalTypes": ["User"],
                        "resourceTypes": ["Photo"],
                    }
                }
            },
        }
    }
    domain = tmp_path / "hr"
    (domain / "requirements").mkdir(parents=True)
    (domain / "policies").mkdir(parents=True)
    (domain / "schema.json").write_text(json.dumps(schema), encoding="utf-8")
    return tmp_path


SCOPE_GENERATE = [
    "--principal",
    "specific",
    "--principal-type",
    "User",
    "--entity-id",
    "alice",
    "--action",
    "named",
    "--action-name",
    "viewPhoto",
    "--resource",
    "specific",
    "--resource-type",
    "Photo",
    "--entity-id",
    "p1",
]

SCOPE_APPLY = [
    "--principal",
    "specific",
    "--principal-type",
    "User",
    "--entity-id",
    "alice",
    "--action",
    "named",
    "--action-name",
    "viewPhoto",
    "--resource",
    "specific",
    "--resource-type",
    "Photo",
    "--entity-id",
    "p1",
]


def _compile_one_policy(workspace: Path) -> None:
    source = workspace / "HR-042.md"
    source.write_text(
        "---\nid: HR-042\ndomain: hr\n---\n\nOnly admins can view photos.\n",
        encoding="utf-8",
    )
    main(["--workspace", str(workspace), "requirement", "add", str(source), "--domain", "hr"])
    main(
        [
            "--workspace",
            str(workspace),
            "policy",
            "generate",
            "HR-042",
            "--domain",
            "hr",
            *SCOPE_GENERATE,
            "--offline",
        ]
    )
    main(
        [
            "--workspace",
            str(workspace),
            "policy",
            "apply",
            "HR-042",
            "--domain",
            "hr",
            *SCOPE_APPLY,
            "--no-scenarios",
        ]
    )


def test_verify_command_passes(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    _compile_one_policy(workspace)
    exit_code = main(["--workspace", str(workspace), "verify", "--domain", "hr"])
    assert exit_code == 0


def test_verify_command_strict_failure(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    exit_code = main(
        ["--workspace", str(workspace), "verify", "--domain", "hr", "--strict"]
    )
    assert exit_code == 1


def test_verify_command_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    workspace = make_workspace(tmp_path)
    main(["--workspace", str(workspace), "--json", "verify", "--domain", "hr"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["domain"] == "hr"


def test_deploy_bundle_writes_to_directory(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    _compile_one_policy(workspace)
    output = tmp_path / "out" / "hr"
    exit_code = main(
        [
            "--workspace",
            str(workspace),
            "deploy",
            "bundle",
            "--domain",
            "hr",
            "--output",
            str(output),
        ]
    )
    assert exit_code == 0
    assert (output / "bundle.cedar").exists()


def test_deploy_push_local(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    _compile_one_policy(workspace)
    target = tmp_path / "deploy" / "hr"
    exit_code = main(
        [
            "--workspace",
            str(workspace),
            "deploy",
            "push",
            "--domain",
            "hr",
            "--target",
            str(target),
        ]
    )
    assert exit_code == 0
    assert (target / "bundle.cedar").exists()


def test_deploy_history_records_previous_pushes(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    _compile_one_policy(workspace)
    target = tmp_path / "deploy" / "hr"
    main(
        [
            "--workspace",
            str(workspace),
            "deploy",
            "push",
            "--domain",
            "hr",
            "--target",
            str(target),
        ]
    )
    exit_code = main(
        [
            "--workspace",
            str(workspace),
            "deploy",
            "history",
            "--domain",
            "hr",
        ]
    )
    assert exit_code == 0


def test_deploy_history_unfiltered(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    exit_code = main(["--workspace", str(workspace), "deploy", "history"])
    assert exit_code == 0


class _RecordingHandler(BaseHTTPRequestHandler):
    received: list[bytes] = []
    status_code = 200
    response_body = b"ok"

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.received.append(body)
        self.send_response(self.status_code)
        self.end_headers()
        self.wfile.write(self.response_body)

    def log_message(self, *_args: object) -> None:
        return


def _build_handler(received: list[bytes], status_code: int, response_body: bytes) -> type:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib API
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            received.append(body)
            self.send_response(status_code)
            self.end_headers()
            self.wfile.write(response_body)

        def log_message(self, *_args: object) -> None:
            return

    return Handler


def test_deploy_push_http(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    _compile_one_policy(workspace)
    received: list[bytes] = []
    handler_class = _build_handler(received, 200, b"ok")
    server = HTTPServer(("127.0.0.1", 0), handler_class)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/cedar"
        exit_code = main(
            [
                "--workspace",
                str(workspace),
                "deploy",
                "push",
                "--domain",
                "hr",
                "--target",
                url,
                "--header",
                "X-Test: yes",
            ]
        )
        assert exit_code == 0
        assert received
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_parse_headers_handles_multiple_entries() -> None:
    assert parse_headers(["Name: Value", "Authorization: Bearer x"]) == {
        "Name": "Value",
        "Authorization": "Bearer x",
    }


def test_parse_headers_rejects_invalid_entries() -> None:
    from cedar_intent import ConfigError

    with pytest.raises(ConfigError):
        parse_headers(["not a header"])


def test_unknown_command_after_verify() -> None:
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["verify", "--domain", "hr", "extra"])
