"""Command-line interface for cedrus.

Each subcommand is implemented as a small handler that operates on a
:class:`~cedrus.space.Space`. The :func:`main` entrypoint returns an
exit code so the process can be wired into CI pipelines without
parsing stdout.

Design:
    The CLI is a thin layer over the public Python API. Every
    subcommand opens the workspace through
    :meth:`~cedrus.space.Space.open` (or constructs it through
    :meth:`~cedrus.space.Space.create` for ``init``), delegates the
    actual work to a workspace method, and returns a JSON-serializable
    dict for humanize/JSON output.

    The CLI is the documented entry-point handler for every
    :class:`~cedrus.error.Error` raised below; the top-level
    :func:`main` translates any of those into a single-line
    ``cedrus: error: ...`` message on stderr and an exit code of 1.

Online and offline modes:
    Generator selection is controlled by three pieces, in this order:

    1. ``--offline`` forces :class:`~cedrus.generate.Offline`.
    2. ``--model <provider/name>`` forces :class:`~cedrus.generate.Llm`.
    3. Otherwise the environment variables ``CEDAR_INTENT_ONLINE`` and
       ``CEDAR_INTENT_MODEL`` decide. ``CEDAR_INTENT_ONLINE=1`` enables
       the LiteLLM generator when ``CEDAR_INTENT_MODEL`` is set;
       otherwise the offline generator runs.

Attributes:
    main: Top-level entry point; returns the process exit code.
    build_parser: Build the top-level :class:`argparse.ArgumentParser`
        with every subcommand wired in.

See Also:
    :mod:`cedrus.space`: Space / typed-object API the CLI delegates
        to.
    :mod:`cedrus.error`: Error types the CLI translates to stderr.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from argparse import Namespace, _SubParsersAction
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from cedrus import Error, Llm, Offline, Space
from cedrus.case import Case
from cedrus.error import Config
from cedrus.scope import Action, Principal, Resource

ONLINE_ENV_VAR = "CEDAR_INTENT_ONLINE"
MODEL_ENV_VAR = "CEDAR_INTENT_MODEL"


def positive_finite_float(value: str) -> float:
    """argparse type for positive finite floats (reject inf/nan/<=0)."""
    try:
        number = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"expected a number, got {value!r}") from error
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError(
            f"value must be a positive finite number, got {value!r}"
        )
    return number


def non_negative_int(value: str) -> int:
    """argparse type for non-negative integers."""
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"expected an integer, got {value!r}") from error
    if number < 0:
        raise argparse.ArgumentTypeError(
            f"value must be non-negative, got {value!r}"
        )
    return number


def positive_int(value: str) -> int:
    """argparse type for positive integers."""
    number = non_negative_int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError(
            f"value must be positive, got {value!r}"
        )
    return number


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser with every subcommand wired in."""
    parser = argparse.ArgumentParser(
        prog="cedrus",
        description="Compile organizational authorization intent into Cedar.",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Space directory (defaults to current directory).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    add_workspace_parser(sub)
    add_domain_parser(sub)
    add_requirement_parser(sub)
    add_policy_parser(sub)
    add_export_parser(sub)
    add_check_parser(sub)
    add_verify_parser(sub)
    add_deploy_parser(sub)
    return parser


def add_workspace_parser(sub: _SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``init`` subcommand."""
    parser = sub.add_parser("init", help="Initialize a new workspace.")
    parser.add_argument("--path", type=str, required=True, help="Space root.")


def add_domain_parser(sub: _SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``domain`` subcommand tree."""
    parser = sub.add_parser("domain", help="Domain operations.")
    sub_domains = parser.add_subparsers(dest="domain_command", required=True)
    add_parser = sub_domains.add_parser("add", help="Create a new domain directory.")
    add_parser.add_argument("name", help="Domain name.")
    sub_domains.add_parser("list", help="List domains present in the workspace.")


def add_requirement_parser(sub: _SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``requirement`` subcommand tree."""
    parser = sub.add_parser("requirement", help="Need operations.")
    sub_reqs = parser.add_subparsers(dest="requirement_command", required=True)
    add_parser = sub_reqs.add_parser("add", help="Add a requirement file.")
    add_parser.add_argument("path", type=Path, help="Path to a Markdown requirement file.")
    add_parser.add_argument(
        "--domain", required=True, help="Domain the requirement belongs to."
    )
    list_parser = sub_reqs.add_parser("list", help="List known requirements.")
    list_parser.add_argument("--domain", help="Filter by domain.")


def add_scope_arguments(
    parser: argparse.ArgumentParser, *, default_principal: str = "any"
) -> None:
    """Register every scope-related flag on ``parser``."""
    parser.add_argument(
        "--principal",
        default=default_principal,
        choices=["any", "type", "specific", "in_group", "is_type"],
        help="Principal scope kind.",
    )
    parser.add_argument(
        "--action",
        default="any",
        choices=["any", "named", "in_group"],
        help="Action scope kind.",
    )
    parser.add_argument(
        "--resource",
        default="any",
        choices=["any", "type", "specific", "in_parent", "is_type"],
        help="Resource scope kind.",
    )
    parser.add_argument("--principal-type", help="Principal entity type name.")
    parser.add_argument("--entity-id", help="Entity id (for specific scope).")
    parser.add_argument("--group-type", help="Group type (for in_group principal).")
    parser.add_argument("--group-id", help="Group id (for in_group principal).")
    parser.add_argument("--action-name", help="Action name (for named action).")
    parser.add_argument("--action-group", help="Action group (for in_group action).")
    parser.add_argument("--resource-type", help="Resource entity type name.")
    parser.add_argument("--parent-type", help="Parent type (for in_parent resource).")
    parser.add_argument("--parent-id", help="Parent id (for in_parent resource).")


def add_policy_parser(sub: _SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``policy`` subcommand tree."""
    parser = sub.add_parser("policy", help="Policy operations.")
    sub_pol = parser.add_subparsers(dest="policy_command", required=True)

    draft_parser = sub_pol.add_parser(
        "draft", help="Build a draft policy from a requirement."
    )
    draft_parser.add_argument("requirement_id", help="Need identifier.")
    draft_parser.add_argument("--domain", required=True, help="Domain name.")
    add_scope_arguments(draft_parser)

    generate_parser = sub_pol.add_parser(
        "generate", help="Generate Cedar source for a draft via the configured generator."
    )
    generate_parser.add_argument("requirement_id", help="Need identifier.")
    generate_parser.add_argument("--domain", required=True)
    add_scope_arguments(generate_parser)
    generate_parser.add_argument("--model", help="LiteLLM model identifier.")
    generate_parser.add_argument(
        "--offline", action="store_true", help="Use Offline."
    )
    generate_parser.add_argument("--timeout", type=positive_finite_float, default=60)
    generate_parser.add_argument("--retries", type=non_negative_int, default=2)
    generate_parser.add_argument("--max-tokens", type=positive_int, default=4096)

    apply_parser = sub_pol.add_parser(
        "apply", help="Validate and persist a previously generated draft."
    )
    apply_parser.add_argument("requirement_id", help="Need identifier.")
    apply_parser.add_argument("--domain", required=True)
    add_scope_arguments(apply_parser)
    apply_parser.add_argument(
        "--no-scenarios", action="store_true", help="Skip running authorization scenarios."
    )


def add_export_parser(sub: _SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``export`` subcommand."""
    parser = sub.add_parser("export", help="Export a compiled domain as Cedar source.")
    parser.add_argument("--domain", required=True)
    parser.add_argument("--output", type=Path, required=True)


def add_check_parser(sub: _SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``check`` subcommand."""
    parser = sub.add_parser("check", help="Validate every domain in the workspace.")
    parser.add_argument("--domain", help="Limit the check to a single domain.")


def add_verify_parser(sub: _SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``verify`` subcommand."""
    parser = sub.add_parser(
        "verify", help="Run static symbolic verification on a domain."
    )
    parser.add_argument("--domain", required=True, help="Domain to verify.")
    parser.add_argument(
        "--strict", action="store_true", help="Exit non-zero on any warning."
    )


def add_deploy_parser(sub: _SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser(
        "deploy", help="Deploy compiled policies to a local directory or HTTP endpoint."
    )
    sub_deploy = parser.add_subparsers(dest="deploy_command", required=True)

    push = sub_deploy.add_parser("push", help="Push a domain's bundle to a target.")
    push.add_argument("--domain", required=True)
    push.add_argument(
        "--target", required=True, help="Local path or http(s) URL."
    )
    push.add_argument("--timeout", type=positive_finite_float, default=30)
    push.add_argument(
        "--header",
        action="append",
        default=[],
        help="HTTP header in 'Name: Value' form (repeatable).",
    )
    push.add_argument(
        "--allow-private-targets",
        action="store_true",
        help="Allow HTTP targets in RFC1918 private network ranges.",
    )
    push.add_argument(
        "--allow-loopback",
        action="store_true",
        help="Allow HTTP targets on loopback addresses (test use only).",
    )
    push.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip the verify-domain gate before deployment.",
    )

    bundle = sub_deploy.add_parser(
        "bundle", help="Write a deployment bundle to a local directory."
    )
    bundle.add_argument("--domain", required=True)
    bundle.add_argument("--output", type=Path, required=True)

    history = sub_deploy.add_parser(
        "history", help="List past deployments, optionally filtered by domain."
    )
    history.add_argument("--domain", help="Filter by domain.")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI with ``argv`` (defaults to ``sys.argv``).

    Args:
        argv: Optional argument vector. When ``None``, ``sys.argv`` is used.

    Returns:
        Process exit code: ``0`` on success, ``1`` when any
        :class:`~cedrus.error.Error` is raised,
        ``2`` for argparse usage errors or unexpected exceptions.
    """
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_event:
        # argparse calls sys.exit on usage errors; surface the exit
        # code so the test/CI can observe it without catching
        # SystemExit.
        return int(exit_event.code) if exit_event.code is not None else 2
    try:
        result, exit_code = run_command(args)
    except Error as error:
        return report_error(args, error)
    except Exception as error:
        return report_unexpected_error(args, error)
    if result is not None:
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print(humanize(result))
    return exit_code


def report_error(args: Namespace, error: Error) -> int:
    """Emit a structured error envelope and return the exit code."""
    message = str(error)
    if getattr(args, "json", False):
        envelope = {
            "error": {
                "type": type(error).__name__,
                "message": message,
            }
        }
        print(json.dumps(envelope, indent=2, default=str), file=sys.stderr)
    else:
        print(f"cedrus: error: {message}", file=sys.stderr)
    return 1


def report_unexpected_error(args: Namespace, error: BaseException) -> int:
    """Wrap unexpected exceptions so CI never sees a raw stack trace."""
    if getattr(args, "json", False):
        envelope = {
            "error": {
                "type": type(error).__name__,
                "message": str(error),
                "unexpected": True,
            }
        }
        print(json.dumps(envelope, indent=2, default=str), file=sys.stderr)
    else:
        print(
            f"cedrus: internal error: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        print(
            "Run with --log-level debug for a full traceback or file an issue.",
            file=sys.stderr,
        )
    return 1


def run_command(args: Namespace) -> tuple[Any, int]:
    """Dispatch a parsed CLI invocation to the matching handler.

    The ``init`` subcommand is handled before workspace open because
    no workspace exists yet. Every other subcommand opens the
    workspace at ``args.workspace``, dispatches the handler via
    ``HANDLERS``, and closes the workspace before returning. The exit
    code comes from the handler (``verify`` returns 1 in strict mode;
    the others return 0).

    Args:
        args: Parsed CLI namespace.

    Returns:
        A tuple ``(result, exit_code)`` where ``result`` is the
        JSON-serializable dict to emit and ``exit_code`` is the
        process exit code.

    Raises:
        Error: For any workspace, storage, generator, or validation
            failure. The CLI's :func:`main` translates these into a
            uniform error message and exit code ``1``.
    """
    if args.command == "init":
        return command_init(args.path), 0
    workspace_path = args.workspace.resolve()
    if not workspace_path.exists():
        raise Config(f"workspace directory does not exist: {workspace_path}")
    workspace = Space.open(workspace_path)
    try:
        handler = HANDLERS.get(args.command)
        if handler is None:
            raise Config(f"unknown command: {args.command}")
        result = handler(workspace, args)
        if isinstance(result, tuple) and len(result) == 2:
            return result
        return result, 0
    finally:
        workspace.close()


def command_init(path: str) -> dict[str, Any]:
    """Initialize a new workspace and report the absolute path.

    Args:
        path: Space root path supplied via ``--path``.

    Returns:
        A dict with an ``"initialized"`` key whose value is the
        resolved absolute path of the new workspace.

    Raises:
        Config: When ``path`` is empty, root, or otherwise invalid.
    """
    text = path.strip()
    if not text or text in {".", "/"}:
        raise Config("init --path must be a non-empty directory path")
    target = Path(text)
    workspace = Space.create(target)
    workspace.close()
    return {"initialized": str(target.resolve())}


def command_domain(workspace: Space, args: Namespace) -> Any:
    """Handle ``domain add`` and ``domain list`` subcommands.

    Polymorphic dispatch on ``args.domain_command``:
    ``add`` initializes a new domain directory; ``list`` enumerates
    the domains present in the workspace.

    Args:
        workspace: Open workspace to operate on.
        args: Parsed CLI namespace; ``args.domain_command`` selects
            the action.

    Returns:
        A dict with the result. For ``add``: ``{"domain": ..., "schema": ...}``.
        For ``list``: ``{"domains": [...]}``.

    Raises:
        Config: When ``args.domain_command`` is unknown or the
            ``add`` identifier is invalid.
    """
    if args.domain_command == "add":
        validate_identifier(args.name, "domain name")
        schema_path = workspace.init_domain(args.name)
        return {"domain": args.name, "schema": str(schema_path)}
    if args.domain_command == "list":
        domains = sorted(
            {
                str(path.parent.name)
                for path in workspace.root.glob("*/schema.json")
                if path.parent.name not in {".cedrus", ""}
            }
        )
        return {"domains": domains}
    raise Config(f"unknown domain command: {args.domain_command}")


def command_requirement(workspace: Space, args: Namespace) -> Any:
    """Handle ``requirement add`` and ``requirement list`` subcommands.

    Polymorphic dispatch on ``args.requirement_command``:
    ``add`` copies a Markdown requirement file into the domain's
    requirements directory and persists it; ``list`` enumerates the
    known requirements.

    Args:
        workspace: Open workspace to operate on.
        args: Parsed CLI namespace; ``args.requirement_command``
            selects the action.

    Returns:
        A dict with the result. For ``add``: ``{"id": ..., "domain": ...}``.
        For ``list``: ``{"requirements": [...]}``.

    Raises:
        Config: When the source file is missing, the ``add``
            identifier is invalid, or ``args.requirement_command`` is
            unknown.
    """
    if args.requirement_command == "add":
        validate_identifier(args.domain, "domain name")
        if not args.path.exists():
            raise Config(f"requirement file not found: {args.path}")
        target = workspace.requirements_directory(args.domain) / args.path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(args.path.read_text(encoding="utf-8"), encoding="utf-8")
        requirement = workspace.add_requirement_file(target)
        return {"id": requirement.id, "domain": requirement.domain}
    if args.requirement_command == "list":
        items = workspace.list_requirements(args.domain)
        return {"requirements": [item.id for item in items]}
    raise Config(f"unknown requirement command: {args.requirement_command}")


def command_policy(workspace: Space, args: Namespace) -> Any:
    """Handle ``policy draft``, ``policy generate``, and ``policy apply`` subcommands.

    Dispatch is keyed on ``args.policy_command``:
    ``draft`` creates a draft, ``generate`` calls the configured
    generator, ``apply`` validates and persists a generated draft.

    Args:
        workspace: Open workspace to operate on.
        args: Parsed CLI namespace; ``args.policy_command`` selects
            the action, ``args.domain`` / ``args.requirement_id`` the
            target requirement, and the scope flags (``--principal``,
            ``--action``, ``--resource``, etc.) are passed through.

    Returns:
        A dict with the result. For ``draft``: ``{"draft": ...}``.
        For ``generate``: ``{"draft": ..., "model": ..., ...}``. For
        ``apply``: ``{"compiled": ...}``.

    Raises:
        Config: When ``args.policy_command`` is unknown or an
            identifier is invalid.
    """
    validate_identifier(args.domain, "domain name")
    validate_identifier(args.requirement_id, "requirement id")
    schema = workspace.load_schema(args.domain)
    handler = POLICY_HANDLERS.get(args.policy_command)
    if handler is None:
        raise Config(f"unknown policy command: {args.policy_command}")
    return handler(workspace, args, schema)


def policy_draft(workspace: Space, args: Namespace, schema: Any) -> Any:
    """``policy draft`` subcommand handler."""
    draft = workspace.create_draft(
        args.requirement_id,
        principal=build_principal(args),
        action=build_action(args),
        resource=build_resource(args),
    )
    return {"draft": draft.to_dict()}


def policy_generate(workspace: Space, args: Namespace, schema: Any) -> Any:
    """``policy generate`` subcommand handler."""
    draft = workspace.create_draft(
        args.requirement_id,
        principal=build_principal(args),
        action=build_action(args),
        resource=build_resource(args),
    )
    generator = build_generator(args)
    existing = workspace.list_existing_policies(args.domain)
    draft, result = workspace.generate_draft(
        draft, schema, generator, existing=existing
    )
    return {
        "draft": draft.to_dict(),
        "model": result.model,
        "request_id": result.request_id,
        "usage": result.usage,
    }


def policy_apply(workspace: Space, args: Namespace, schema: Any) -> Any:
    """``policy apply`` subcommand handler."""
    scopes = (
        build_principal(args),
        build_action(args),
        build_resource(args),
    )
    scenarios: list[Case] = []
    if not getattr(args, "no_scenarios", False):
        scenarios = workspace.load_scenarios(args.domain)
    compiled = workspace.apply_for_requirement(
        args.requirement_id, schema, scopes=scopes, scenarios=scenarios
    )
    return {"compiled": compiled.to_dict()}


#: Polymorphic dispatch table: ``policy_command`` -> handler.
#: Handlers take ``(workspace, args, schema)`` and return the
#: subcommand's result dict.
POLICY_HANDLERS: dict[str, Any] = {
    "draft": policy_draft,
    "generate": policy_generate,
    "apply": policy_apply,
}


def command_export(workspace: Space, args: Namespace) -> Any:
    """Export the domain's compiled Cedar to ``args.output``.

    Args:
        workspace: Open workspace to operate on.
        args: Parsed CLI namespace; ``args.domain`` selects the
            domain, ``args.output`` is the destination path.

    Returns:
        A dict with ``"domain"`` and ``"output"`` keys.

    Raises:
        Config: When the domain identifier is invalid.
    """
    validate_identifier(args.domain, "domain name")
    schema = workspace.load_schema(args.domain)
    workspace.validate_policies(args.domain, schema)
    output = workspace.export_domain(args.domain, args.output)
    return {"domain": args.domain, "output": str(output)}


def command_check(workspace: Space, args: Namespace) -> Any:
    """Run validation across every domain (or the specified one).

    Args:
        workspace: Open workspace to operate on.
        args: Parsed CLI namespace; ``args.domain`` (when set) limits
            the check to a single domain.

    Returns:
        A dict with ``"passed"`` (overall bool) and ``"domains"``
        (per-domain result dict, with ``"passed"`` and optionally
        ``"error"`` keys).
    """
    if args.domain:
        domains = [args.domain]
    else:
        domains = sorted(
            {
                path.parent.name
                for path in workspace.root.glob("*/schema.json")
                if path.parent.name not in {".cedrus", ""}
            }
        )
    results: dict[str, Any] = {}
    for domain in domains:
        try:
            schema = workspace.load_schema(domain)
            workspace.add_requirement_directory(domain)
            workspace.import_existing_policies(domain)
            workspace.validate_policies(domain, schema)
            results[domain] = {"passed": True}
        except Error as error:
            results[domain] = {"passed": False, "error": str(error)}
    overall = all(result["passed"] for result in results.values())
    return {"passed": overall, "domains": results}


def command_verify(workspace: Space, args: Namespace) -> tuple[Any, int]:
    """Run verification for ``args.domain`` and return its report.

    Args:
        workspace: Open workspace to operate on.
        args: Parsed CLI namespace; ``args.domain`` selects the domain
            and ``args.strict`` flips the exit code on warnings.

    Returns:
        A tuple ``(report_dict, exit_code)`` where ``exit_code`` is
        ``1`` when ``--strict`` is set and the report has warnings,
        else ``0``.
    """
    validate_identifier(args.domain, "domain name")
    schema = workspace.load_schema(args.domain)
    report = workspace.verify_domain(args.domain, schema)
    exit_code = 1 if args.strict and not report.passed else 0
    return report.to_dict(), exit_code


def command_deploy(workspace: Space, args: Namespace) -> tuple[Any, int]:
    """Handle the three ``deploy`` subcommands polymorphically.

    Dispatch is keyed on ``args.deploy_command``:
    ``push`` calls :meth:`Space.deploy`, ``bundle`` calls
    :meth:`Space.write_bundle`, and ``history`` calls
    :meth:`Space.list_deployments`.

    Args:
        workspace: Open workspace to operate on.
        args: Parsed CLI namespace; ``args.deploy_command`` selects
            the action.

    Returns:
        A tuple ``(result, exit_code)`` where ``result`` is the
        subcommand-specific dict to emit and ``exit_code`` is always
        ``0`` for the three subcommands.

    Raises:
        Config: When ``args.deploy_command`` is unknown.
    """
    # ``deploy history`` accepts an optional domain filter; only
    # validate when the user actually supplied one.
    domain = getattr(args, "domain", None)
    if domain:
        validate_identifier(domain, "domain name")
    handler = DEPLOY_HANDLERS.get(args.deploy_command)
    if handler is None:
        raise Config(f"unknown deploy command: {args.deploy_command}")
    return handler(workspace, args), 0


def deploy_push(workspace: Space, args: Namespace) -> Any:
    """``deploy push`` subcommand handler."""
    headers = parse_headers(getattr(args, "header", []) or [])
    record = workspace.deploy(
        args.domain,
        args.target,
        timeout=getattr(args, "timeout", 30),
        headers=headers,
        skip_verify=getattr(args, "skip_verify", False),
        allow_private_targets=getattr(args, "allow_private_targets", False),
        allow_loopback=getattr(args, "allow_loopback", False),
    )
    return {"deployment": deployment_to_dict(record)}


def deploy_bundle(workspace: Space, args: Namespace) -> Any:
    """``deploy bundle`` subcommand handler."""
    manifest = workspace.build_bundle(args.domain)
    workspace.write_bundle(manifest, args.output)
    return {"domain": args.domain, "output": str(args.output)}


def deploy_history(workspace: Space, args: Namespace) -> Any:
    """``deploy history`` subcommand handler."""
    records = workspace.list_deployments(getattr(args, "domain", None))
    return {"deployments": [deployment_to_dict(record) for record in records]}


#: Polymorphic dispatch table: ``deploy_command`` -> handler.
#: Handlers take ``(workspace, args)`` and return the subcommand's
#: result dict.
DEPLOY_HANDLERS: dict[str, Any] = {
    "push": deploy_push,
    "bundle": deploy_bundle,
    "history": deploy_history,
}


#: Polymorphic dispatch table: top-level ``command`` -> handler.
#: Handlers take ``(workspace, args)`` and return ``(result,
#: exit_code)``. ``init`` is the only subcommand that does not go
#: through this table; it is handled inline in :func:`run_command`
#: because there is no workspace to open before it runs.
HANDLERS: dict[str, Any] = {
    "domain": command_domain,
    "requirement": command_requirement,
    "policy": command_policy,
    "export": command_export,
    "check": command_check,
    "verify": command_verify,
    "deploy": command_deploy,
}


def parse_headers(raw: list[str]) -> dict[str, str]:
    """Parse ``["Name: Value", ...]`` into a header dictionary.

    Args:
        raw: Sequence of ``"Name: Value"`` strings (typically
            collected from ``--header`` CLI flags).

    Returns:
        A dict mapping header name to value.

    Raises:
        Config: When a header is missing a colon, has an empty
            name, contains CR/LF in either name or value, or has a
            name longer than 256 characters / value longer than 8192.
    """
    parsed: dict[str, str] = {}
    for entry in raw:
        if ":" not in entry:
            raise Config(f"invalid header (expected 'Name: Value'): {entry!r}")
        name, _, value = entry.partition(":")
        name = name.strip()
        value = value.strip()
        if not name:
            raise Config("header name must be non-empty")
        if "\r" in name or "\n" in name or "\r" in value or "\n" in value:
            raise Config(
                f"header contains CR/LF (CVE-style injection): {entry!r}"
            )
        if len(name) > 256:
            raise Config(f"header name {name!r} exceeds 256 characters")
        if len(value) > 8192:
            raise Config(f"header value for {name!r} exceeds 8192 characters")
        parsed[name] = value
    return parsed


def validate_identifier(name: str, kind: str) -> str:
    """Validate that ``name`` is a safe workspace identifier.

    Identifiers are used in filesystem paths (domain names,
    requirement ids) so anything outside a conservative alphabet is
    rejected to prevent path traversal or NUL injection.

    Args:
        name: Identifier supplied by the user.
        kind: Human-readable kind for error messages
            (e.g., ``"domain"`` or ``"requirement id"``).

    Returns:
        The validated identifier (unchanged).

    Raises:
        Config: When ``name`` is empty, too long, or contains
            characters outside ``[A-Za-z0-9._-]``.
    """
    if not name or not name.strip():
        raise Config(f"{kind} must be non-empty")
    if len(name) > 64:
        raise Config(f"{kind} must be at most 64 characters")
    for ch in name:
        if not (ch.isalnum() or ch in "._-"):
            raise Config(
                f"{kind} {name!r} contains illegal character {ch!r}; "
                "use only letters, digits, '.', '_', and '-'"
            )
    return name


def deployment_to_dict(record: Any) -> dict[str, Any]:
    """Serialize a :class:`~cedrus.deploy.Record` for CLI output.

    Args:
        record: The :class:`Record` to serialize.

    Returns:
        A dict with ``id``, ``domain``, ``target``, ``target_kind``,
        ``bundle_hash``, ``status``, ``response`` and ``created_at``
        keys.
    """
    return {
        "id": record.id,
        "domain": record.domain,
        "target": record.target,
        "target_kind": record.target_kind,
        "bundle_hash": record.bundle_hash,
        "status": record.status,
        "response": dict(record.response),
        "created_at": record.created_at.isoformat(),
    }


def build_generator(args: Namespace) -> Any:
    """Select the right generator based on flags and environment.

    Dispatch:
    * ``--offline`` forces :class:`~cedrus.generate.Offline`.
    * ``--model <provider/name>`` forces :class:`~cedrus.generate.Llm`.
    * Otherwise the environment variables ``CEDAR_INTENT_ONLINE`` and
      ``CEDAR_INTENT_MODEL`` decide.

    Args:
        args: Parsed CLI namespace; reads ``args.offline``,
            ``args.model``, ``args.timeout``, ``args.retries`` and
            ``args.max_tokens`` when constructing the LLM.

    Returns:
        A ready-to-use :class:`~cedrus.generate.Offline` or
        :class:`~cedrus.generate.Llm` instance.
    """
    model = getattr(args, "model", None) or os.getenv(MODEL_ENV_VAR)
    online = os.getenv(ONLINE_ENV_VAR, "").lower() in {"1", "true", "yes"}
    if getattr(args, "offline", False):
        return Offline()
    if not online or not model:
        return Offline()
    return Llm(
        model=model,
        timeout=getattr(args, "timeout", 60),
        retries=getattr(args, "retries", 2),
        max_tokens=getattr(args, "max_tokens", 4096),
    )


def build_principal(args: Namespace) -> Principal:
    """Build a :class:`Principal` from parsed CLI arguments.

    Args:
        args: Parsed CLI namespace; reads ``args.principal``,
            ``args.principal_type``, ``args.entity_id``,
            ``args.group_type``, ``args.group_id``.

    Returns:
        A :class:`~cedrus.scope.Principal` configured from the flags.
    """
    return Principal(
        kind=args.principal,
        type_name=args.principal_type,
        entity_id=args.entity_id,
        group_type=args.group_type,
        group_id=args.group_id,
    )


def build_action(args: Namespace) -> Action:
    """Build an :class:`Action` from parsed CLI arguments.

    Args:
        args: Parsed CLI namespace; reads ``args.action``,
            ``args.action_name``, ``args.action_group``.

    Returns:
        A :class:`~cedrus.scope.Action` configured from the flags.
    """
    return Action(
        kind=args.action,
        name=args.action_name,
        group=args.action_group,
    )


def build_resource(args: Namespace) -> Resource:
    """Build a :class:`Resource` from parsed CLI arguments.

    Args:
        args: Parsed CLI namespace; reads ``args.resource``,
            ``args.resource_type``, ``args.entity_id``,
            ``args.parent_type``, ``args.parent_id``.

    Returns:
        A :class:`~cedrus.scope.Resource` configured from the flags.
    """
    return Resource(
        kind=args.resource,
        type_name=args.resource_type,
        entity_id=args.entity_id,
        parent_type=args.parent_type,
        parent_id=args.parent_id,
    )


def humanize(payload: Any) -> str:
    """Render a structured CLI result for human-friendly output.

    Polymorphic on the payload shape: each subcommand result type
    has its own one-line humanizer. The function dispatches via
    ``HUMANIZERS``; payloads that don't match any specific shape fall
    through to the JSON dump.

    Args:
        payload: The structured result dict returned by a subcommand
            handler (or any other JSON-serializable value).

    Returns:
        A single-line string for human consumption.
    """
    if not isinstance(payload, dict):
        return json.dumps(payload, indent=2, default=str)
    for predicate, render in HUMANIZERS:
        if predicate(payload):
            return render(payload)
    return json.dumps(payload, indent=2, default=str)


def has_compiled(payload: dict[str, Any]) -> bool:
    return "compiled" in payload


def has_draft(payload: dict[str, Any]) -> bool:
    return "draft" in payload


def has_domain_export(payload: dict[str, Any]) -> bool:
    return "domain" in payload and "output" in payload


def has_check_report(payload: dict[str, Any]) -> bool:
    return "passed" in payload and "domains" in payload


def has_initialized(payload: dict[str, Any]) -> bool:
    return "initialized" in payload


def has_requirements(payload: dict[str, Any]) -> bool:
    return "requirements" in payload


def has_domains(payload: dict[str, Any]) -> bool:
    return "domains" in payload


def has_stored_requirement(payload: dict[str, Any]) -> bool:
    return "id" in payload and "domain" in payload


def humanize_check_report(payload: dict[str, Any]) -> str:
    """Render the ``check`` subcommand result."""
    domains = payload["domains"]
    failures = [name for name, info in domains.items() if not info["passed"]]
    if not failures:
        return f"All {len(domains)} domain(s) passed validation."
    return f"Failed: {', '.join(failures)}"


#: Polymorphic dispatch table: ``(predicate, render)`` pairs in
#: priority order. The first predicate that returns ``True`` wins;
#: payloads that match no predicate fall through to the JSON dump.
HUMANIZERS: list[tuple[Any, Any]] = [
    (has_compiled, lambda p: f"Compiled policy {p['compiled']['id']} ({p['compiled']['domain']})."),
    (has_draft, lambda p: (
        f"Draft policy {p['draft']['id']} for requirement "
        f"{p['draft']['requirement_id']} in domain {p['draft']['domain']}."
    )),
    (has_domain_export, lambda p: f"Exported {p['domain']} to {p['output']}."),
    (has_check_report, humanize_check_report),
    (has_initialized, lambda p: f"Initialized workspace at {p['initialized']}."),
    (has_requirements, lambda p: join_or_none("Requirements", p["requirements"])),
    (has_domains, lambda p: join_or_none("Domains", p["domains"])),
    (has_stored_requirement, lambda p: f"Stored requirement {p['id']} for domain {p['domain']}."),
]


def join_or_none(label: str, items: list[str]) -> str:
    """Render ``label: a, b, c`` or ``label: (none)`` depending on ``items``."""
    return f"{label}: {', '.join(items)}" if items else f"{label}: (none)"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
