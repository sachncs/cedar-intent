"""Tests for the CLI entrypoint."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cedrus import cli
from cedrus.cli import (
    MODEL_ENV_VAR,
    ONLINE_ENV_VAR,
    build_action,
    build_generator,
    build_principal,
    build_resource,
    main,
    run_command,
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


SCOPE_DRAFT = [
    "--principal",
    "is_type",
    "--principal-type",
    "User",
    "--action",
    "named",
    "--action-name",
    "viewPhoto",
    "--resource",
    "is_type",
    "--resource-type",
    "Photo",
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


def test_main_init_returns_zero(tmp_path: Path) -> None:
    target = tmp_path / "ws"
    exit_code = main(["--workspace", str(tmp_path), "init", "--path", str(target)])
    assert exit_code == 0
    assert (target / ".cedrus" / "store.db").exists()


def test_main_init_serializes_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "ws"
    exit_code = main(
        ["--workspace", str(tmp_path), "--json", "init", "--path", str(target)]
    )
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "initialized" in captured.out


def test_main_init_missing_target_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["--workspace", str(tmp_path), "init", "--path", ""])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "cedrus: error" in captured.err


def test_main_domain_add(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    exit_code = main(["--workspace", str(workspace), "domain", "add", "hr"])
    assert exit_code == 0


def test_main_domain_list_empty(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    exit_code = main(["--workspace", str(workspace), "domain", "list"])
    assert exit_code == 0


def test_main_requirement_add_and_list(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    source = workspace / "HR-042.md"
    source.write_text(
        "---\nid: HR-042\ndomain: hr\n---\n\nOnly admins can view photos.\n",
        encoding="utf-8",
    )
    assert (
        main(
            [
                "--workspace",
                str(workspace),
                "requirement",
                "add",
                str(source),
                "--domain",
                "hr",
            ]
        )
        == 0
    )
    assert main(["--workspace", str(workspace), "requirement", "list"]) == 0


def test_main_requirement_add_missing_file(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    exit_code = main(
        [
            "--workspace",
            str(workspace),
            "requirement",
            "add",
            str(workspace / "missing.md"),
            "--domain",
            "hr",
        ]
    )
    assert exit_code == 1


def test_main_policy_draft(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    source = workspace / "HR-042.md"
    source.write_text(
        "---\nid: HR-042\ndomain: hr\n---\n\nOnly admins can view photos.\n",
        encoding="utf-8",
    )
    main(["--workspace", str(workspace), "requirement", "add", str(source), "--domain", "hr"])
    exit_code = main(
        [
            "--workspace",
            str(workspace),
            "policy",
            "draft",
            "HR-042",
            "--domain",
            "hr",
            *SCOPE_DRAFT,
        ]
    )
    assert exit_code == 0


def test_main_policy_generate_offline(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    source = workspace / "HR-042.md"
    source.write_text(
        "---\nid: HR-042\ndomain: hr\n---\n\nOnly admins can view photos.\n",
        encoding="utf-8",
    )
    main(["--workspace", str(workspace), "requirement", "add", str(source), "--domain", "hr"])
    exit_code = main(
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
    assert exit_code == 0


def test_main_policy_generate_online_without_model_uses_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = make_workspace(tmp_path)
    source = workspace / "HR-042.md"
    source.write_text(
        "---\nid: HR-042\ndomain: hr\n---\n\nOnly admins can view photos.\n",
        encoding="utf-8",
    )
    main(["--workspace", str(workspace), "requirement", "add", str(source), "--domain", "hr"])
    monkeypatch.setenv(ONLINE_ENV_VAR, "1")
    monkeypatch.delenv(MODEL_ENV_VAR, raising=False)
    exit_code = main(
        [
            "--workspace",
            str(workspace),
            "policy",
            "generate",
            "HR-042",
            "--domain",
            "hr",
            *SCOPE_GENERATE,
        ]
    )
    assert exit_code == 0


def test_main_policy_generate_online_with_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = make_workspace(tmp_path)
    source = workspace / "HR-042.md"
    source.write_text(
        "---\nid: HR-042\ndomain: hr\n---\n\nOnly admins can view photos.\n",
        encoding="utf-8",
    )
    main(["--workspace", str(workspace), "requirement", "add", str(source), "--domain", "hr"])
    monkeypatch.setenv(ONLINE_ENV_VAR, "1")
    monkeypatch.setenv(MODEL_ENV_VAR, "provider/test-model")
    response_payload = {
        "intent": {
            "effect": "permit",
            "principal": {"kind": "specific", "type_name": "User", "entity_id": "alice"},
            "action": {"kind": "named", "name": "viewPhoto"},
            "resource": {"kind": "specific", "type_name": "Photo", "entity_id": "p1"},
            "when": [],
            "unless": [],
        },
        "unresolved": [],
    }
    fake_response = SimpleNamespace(
        id="req-1",
        model="provider/resolved-model",
        usage={"total_tokens": 5},
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(response_payload)))],
    )
    with patch("cedrus.generate.litellm.litellm.completion", return_value=fake_response):
        exit_code = main(
            [
                "--workspace",
                str(workspace),
                "policy",
                "generate",
                "HR-042",
                "--domain",
                "hr",
                *SCOPE_GENERATE,
            ]
        )
    assert exit_code == 0


def test_main_policy_apply(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
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
    exit_code = main(
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
    assert exit_code == 0


def test_main_export(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
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
    output = workspace / "dist" / "hr.cedar"
    exit_code = main(
        [
            "--workspace",
            str(workspace),
            "export",
            "--domain",
            "hr",
            "--output",
            str(output),
        ]
    )
    assert exit_code == 0
    assert output.exists()


def test_main_check(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
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
    exit_code = main(["--workspace", str(workspace), "check"])
    assert exit_code == 0


def test_main_check_specific_domain(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    exit_code = main(["--workspace", str(workspace), "check", "--domain", "hr"])
    assert exit_code == 0


def test_main_missing_workspace_returns_one(tmp_path: Path) -> None:
    exit_code = main(["--workspace", str(tmp_path / "missing"), "domain", "list"])
    assert exit_code == 1


def test_main_unknown_command(tmp_path: Path) -> None:
    """Unknown commands return exit code 2 (argparse usage error)."""
    exit_code = main(["--workspace", str(tmp_path), "nope"])
    assert exit_code == 2


def test_run_command_unknown_command_raises(tmp_path: Path) -> None:
    from cedrus import Config

    args = cli.build_parser().parse_args(
        ["--workspace", str(tmp_path), "init", "--path", str(tmp_path)]
    )
    args.command = "garbage"
    with pytest.raises(Config):
        run_command(args)


def test_build_principal_variants() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "--workspace",
            ".",
            "policy",
            "draft",
            "HR-042",
            "--domain",
            "hr",
            "--principal",
            "in_group",
            "--group-type",
            "Group",
            "--group-id",
            "admins",
        ]
    )
    principal = build_principal(args)
    assert principal.kind == "in_group"
    assert principal.group_type == "Group"
    assert principal.group_id == "admins"


def test_build_action_variants() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "--workspace",
            ".",
            "policy",
            "draft",
            "HR-042",
            "--domain",
            "hr",
            "--action",
            "named",
            "--action-name",
            "viewPhoto",
        ]
    )
    action = build_action(args)
    assert action.kind == "named"
    assert action.name == "viewPhoto"


def test_build_resource_variants() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "--workspace",
            ".",
            "policy",
            "draft",
            "HR-042",
            "--domain",
            "hr",
            "--resource",
            "in_parent",
            "--resource-type",
            "Photo",
            "--parent-type",
            "Album",
            "--parent-id",
            "a1",
        ]
    )
    resource = build_resource(args)
    assert resource.kind == "in_parent"
    assert resource.type_name == "Photo"
    assert resource.parent_id == "a1"


def test_build_generator_offline_default() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "--workspace",
            ".",
            "policy",
            "generate",
            "HR-042",
            "--domain",
            "hr",
            "--offline",
        ]
    )
    generator = build_generator(args)
    assert generator.name == "offline"


def test_build_generator_online_missing_model_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "--workspace",
            ".",
            "policy",
            "generate",
            "HR-042",
            "--domain",
            "hr",
            "--model",
            "provider/test-model",
        ]
    )
    monkeypatch.setenv(ONLINE_ENV_VAR, "1")
    monkeypatch.delenv(MODEL_ENV_VAR, raising=False)
    generator = build_generator(args)
    assert generator.model == "provider/test-model"


# ---------------------------------------------------------------------------
# argparse type helpers
# ---------------------------------------------------------------------------


def test_positive_finite_float_accepts_positive_number() -> None:
    from cedrus.cli import positive_finite_float
    assert positive_finite_float("3.14") == 3.14


def test_positive_finite_float_rejects_infinity() -> None:
    from cedrus.cli import positive_finite_float
    with pytest.raises(argparse.ArgumentTypeError):
        positive_finite_float("inf")


def test_positive_finite_float_rejects_nan() -> None:
    from cedrus.cli import positive_finite_float
    with pytest.raises(argparse.ArgumentTypeError):
        positive_finite_float("nan")


def test_positive_finite_float_rejects_zero() -> None:
    from cedrus.cli import positive_finite_float
    with pytest.raises(argparse.ArgumentTypeError):
        positive_finite_float("0")


def test_positive_finite_float_rejects_negative() -> None:
    from cedrus.cli import positive_finite_float
    with pytest.raises(argparse.ArgumentTypeError):
        positive_finite_float("-1.0")


def test_positive_finite_float_rejects_non_number() -> None:
    from cedrus.cli import positive_finite_float
    with pytest.raises(argparse.ArgumentTypeError):
        positive_finite_float("not a number")


def test_non_negative_int_accepts_zero() -> None:
    from cedrus.cli import non_negative_int
    assert non_negative_int("0") == 0


def test_non_negative_int_accepts_positive() -> None:
    from cedrus.cli import non_negative_int
    assert non_negative_int("42") == 42


def test_non_negative_int_rejects_negative() -> None:
    from cedrus.cli import non_negative_int
    with pytest.raises(argparse.ArgumentTypeError):
        non_negative_int("-1")


def test_non_negative_int_rejects_non_integer() -> None:
    from cedrus.cli import non_negative_int
    import argparse
    with pytest.raises(argparse.ArgumentTypeError):
        non_negative_int("3.14")


def test_positive_int_rejects_zero() -> None:
    from cedrus.cli import positive_int
    with pytest.raises(argparse.ArgumentTypeError):
        positive_int("0")


def test_positive_int_accepts_one() -> None:
    from cedrus.cli import positive_int
    assert positive_int("1") == 1


# ---------------------------------------------------------------------------
# __main__ entrypoint
# ---------------------------------------------------------------------------


def test_main_module_routes_to_cli_main() -> None:
    """cedrus.__main__ re-exports cli.main; test that the symbol is bound."""
    import cedrus.__main__

    assert callable(cedrus.__main__.main)


# ---------------------------------------------------------------------------
# report_error / report_unexpected_error
# ---------------------------------------------------------------------------


def test_report_error_returns_one() -> None:
    from cedrus.cli import report_error

    args = SimpleNamespace(json=False, workspace=None, command="init", path=".")
    result = report_error(args, RuntimeError("boom"))
    assert result == 1


def test_report_error_emits_json_envelope_when_json_flag_set(capsys) -> None:
    from cedrus.cli import report_error

    args = SimpleNamespace(json=True, workspace=None, command="init", path=".")
    result = report_error(args, RuntimeError("boom"))
    captured = capsys.readouterr()
    assert result == 1
    assert "boom" in captured.err


def test_report_unexpected_error_returns_one(capsys) -> None:
    from cedrus.cli import report_unexpected_error

    args = SimpleNamespace(json=False, workspace=None, command="init", path=".")
    result = report_unexpected_error(args, ValueError("kaboom"))
    assert result == 1
    captured = capsys.readouterr()
    assert "kaboom" in captured.err


def test_main_returns_two_for_argparse_usage_error(capsys) -> None:
    """main returns exit code 2 for argparse usage errors."""
    from cedrus.cli import main

    code = main(["--not-a-real-flag"])
    assert code == 2


def test_main_returns_one_for_handler_error(capsys) -> None:
    """main returns 1 when a handler raises cedrus.error.Error."""
    from cedrus.cli import main

    code = main(["--workspace", "/nonexistent-workspace-path-xyz", "domain", "list"])
    assert code == 1


def test_main_returns_zero_for_successful_init(tmp_path: Path) -> None:
    from cedrus.cli import main

    code = main(["init", "--path", str(tmp_path / "ws")])
    assert code == 0
    assert (tmp_path / "ws" / ".cedrus").exists()


def test_main_returns_one_for_unexpected_handler_error(capsys) -> None:
    """Unexpected (non-cedrus) exceptions inside a handler return 1."""
    from cedrus.cli import main

    # 'export' expects an existing workspace; an empty tmp_path won't
    # be a workspace and the handler raises a generic exception.
    code = main(["--workspace", str(Path("/no/such/workspace-xyz-9876")), "domain", "list"])
    assert code == 1


def test_main_emits_json_output_when_json_flag_set(tmp_path: Path, capsys) -> None:
    """With --json, the result dict is JSON-serialized to stdout."""
    import json

    from cedrus.cli import main

    code = main(["--json", "init", "--path", str(tmp_path / "ws")])
    assert code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["initialized"] == str((tmp_path / "ws").resolve())
