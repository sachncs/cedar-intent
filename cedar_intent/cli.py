"""Command-line interface for cedar-intent.

Each subcommand is implemented as a small handler that operates on a
:class:`Workspace`. The :func:`main` entrypoint returns an exit code so
the process can be wired into CI pipelines without parsing stdout.

Design
------

The CLI is a thin layer over the public Python API. Every subcommand
opens the workspace through :meth:`Workspace.open` (or constructs it
through :meth:`Workspace.create` for ``init``), delegates the actual
work to a workspace method, and returns a JSON-serializable dict for
humanize/JSON output.

The CLI is the documented entry-point handler for every
:class:`~cedar_intent.errors.CedarIntentError` raised below; the
top-level :func:`main` translates any of those into a single-line
``cedar-intent: error: ...`` message on stderr and an exit code of 1.

Online and offline modes
------------------------

Generator selection is controlled by three pieces, in this order:

1. ``--offline`` forces :class:`~cedar_intent.generator.OfflineGenerator`.
2. ``--model <provider/name>`` forces :class:`~cedar_intent.generator.LiteLLMGenerator`.
3. Otherwise the environment variables ``CEDAR_INTENT_ONLINE`` and
   ``CEDAR_INTENT_MODEL`` decide. ``CEDAR_INTENT_ONLINE=1`` enables the
   LiteLLM generator when ``CEDAR_INTENT_MODEL`` is set; otherwise the
   offline generator runs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from argparse import Namespace, _SubParsersAction
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import CedarIntentError, LiteLLMGenerator, OfflineGenerator, Workspace
from .errors import ConfigError
from .scenarios import Scenario
from .scopes import ActionScope, PrincipalScope, ResourceScope

ONLINE_ENV_VAR = "CEDAR_INTENT_ONLINE"
MODEL_ENV_VAR = "CEDAR_INTENT_MODEL"


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser with every subcommand wired in."""
    parser = argparse.ArgumentParser(
        prog="cedar-intent",
        description="Compile organizational authorization intent into Cedar.",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Workspace directory (defaults to current directory).",
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
    parser.add_argument("--path", type=str, required=True, help="Workspace root.")


def add_domain_parser(sub: _SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``domain`` subcommand tree."""
    parser = sub.add_parser("domain", help="Domain operations.")
    sub_domains = parser.add_subparsers(dest="domain_command", required=True)
    add_parser = sub_domains.add_parser("add", help="Create a new domain directory.")
    add_parser.add_argument("name", help="Domain name.")
    sub_domains.add_parser("list", help="List domains present in the workspace.")


def add_requirement_parser(sub: _SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``requirement`` subcommand tree."""
    parser = sub.add_parser("requirement", help="Requirement operations.")
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
    draft_parser.add_argument("requirement_id", help="Requirement identifier.")
    draft_parser.add_argument("--domain", required=True, help="Domain name.")
    add_scope_arguments(draft_parser)

    generate_parser = sub_pol.add_parser(
        "generate", help="Generate Cedar source for a draft via the configured generator."
    )
    generate_parser.add_argument("requirement_id", help="Requirement identifier.")
    generate_parser.add_argument("--domain", required=True)
    add_scope_arguments(generate_parser)
    generate_parser.add_argument("--model", help="LiteLLM model identifier.")
    generate_parser.add_argument(
        "--offline", action="store_true", help="Use OfflineGenerator."
    )
    generate_parser.add_argument("--timeout", type=float, default=60)
    generate_parser.add_argument("--retries", type=int, default=2)
    generate_parser.add_argument("--max-tokens", type=int, default=4096)

    apply_parser = sub_pol.add_parser(
        "apply", help="Validate and persist a previously generated draft."
    )
    apply_parser.add_argument("requirement_id", help="Requirement identifier.")
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
    """Register the ``deploy`` subcommand tree."""
    parser = sub.add_parser(
        "deploy", help="Deploy compiled policies to a local directory or HTTP endpoint."
    )
    sub_deploy = parser.add_subparsers(dest="deploy_command", required=True)

    push = sub_deploy.add_parser("push", help="Push a domain's bundle to a target.")
    push.add_argument("--domain", required=True)
    push.add_argument(
        "--target", required=True, help="Local path or http(s) URL."
    )
    push.add_argument("--timeout", type=float, default=30)
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
        :class:`~cedar_intent.errors.CedarIntentError` is raised,
        ``2`` for argparse usage errors.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result, exit_code = run_command(args)
    except CedarIntentError as error:
        print(f"cedar-intent: error: {error}", file=sys.stderr)
        return 1
    if result is not None:
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print(humanize(result))
    return exit_code


def run_command(args: Namespace) -> tuple[Any, int]:
    """Dispatch a parsed CLI invocation to the matching handler.

    The ``init`` subcommand is handled before workspace open because
    no workspace exists yet. Every other subcommand opens the
    workspace at ``args.workspace``, dispatches the handler, and
    closes the workspace before returning. The exit code comes from
    the handler (``verify`` returns 1 in strict mode; the others
    return 0).

    Args:
        args: Parsed CLI namespace.

    Returns:
        A tuple ``(result, exit_code)`` where ``result`` is the
        JSON-serializable dict to emit and ``exit_code`` is the process
        exit code.

    Raises:
        CedarIntentError: For any workspace, storage, generator, or
            validation failure. The CLI's :func:`main` translates these
            into a uniform error message and exit code ``1``.
    """
    workspace_path = args.workspace.resolve()
    if args.command == "init":
        return command_init(args.path), 0
    if not workspace_path.exists():
        raise ConfigError(f"workspace directory does not exist: {workspace_path}")
    workspace = Workspace.open(workspace_path)
    try:
        if args.command == "domain":
            return command_domain(workspace, args), 0
        if args.command == "requirement":
            return command_requirement(workspace, args), 0
        if args.command == "policy":
            return command_policy(workspace, args), 0
        if args.command == "export":
            return command_export(workspace, args), 0
        if args.command == "check":
            return command_check(workspace, args), 0
        if args.command == "verify":
            return command_verify(workspace, args)
        if args.command == "deploy":
            return command_deploy(workspace, args)
    finally:
        workspace.close()
    raise ConfigError(f"unknown command: {args.command}")


def command_init(path: str) -> dict[str, Any]:
    """Initialize a new workspace and report the absolute path."""
    text = path.strip()
    if not text or text in {".", "/"}:
        raise ConfigError("init --path must be a non-empty directory path")
    target = Path(text)
    workspace = Workspace.create(target)
    workspace.close()
    return {"initialized": str(target.resolve())}


def command_domain(workspace: Workspace, args: Namespace) -> Any:
    """Handle ``domain add`` and ``domain list`` subcommands."""
    if args.domain_command == "add":
        schema_path = workspace.init_domain(args.name)
        return {"domain": args.name, "schema": str(schema_path)}
    if args.domain_command == "list":
        domains = sorted(
            {
                str(path.parent.name)
                for path in workspace.root.glob("*/schema.json")
                if path.parent.name not in {".cedar-intent", ""}
            }
        )
        return {"domains": domains}
    raise ConfigError(f"unknown domain command: {args.domain_command}")


def command_requirement(workspace: Workspace, args: Namespace) -> Any:
    """Handle ``requirement add`` and ``requirement list`` subcommands."""
    if args.requirement_command == "add":
        if not args.path.exists():
            raise ConfigError(f"requirement file not found: {args.path}")
        target = workspace.requirements_directory(args.domain) / args.path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(args.path.read_text(encoding="utf-8"), encoding="utf-8")
        requirement = workspace.add_requirement_file(target)
        return {"id": requirement.id, "domain": requirement.domain}
    if args.requirement_command == "list":
        items = workspace.list_requirements(args.domain)
        return {"requirements": [item.id for item in items]}
    raise ConfigError(f"unknown requirement command: {args.requirement_command}")


def command_policy(workspace: Workspace, args: Namespace) -> Any:
    """Handle ``policy draft``, ``policy generate``, and ``policy apply`` subcommands."""
    schema = workspace.load_schema(args.domain)
    if args.policy_command == "draft":
        draft = workspace.create_draft(
            args.requirement_id,
            principal=build_principal(args),
            action=build_action(args),
            resource=build_resource(args),
        )
        return {"draft": draft.to_dict()}
    if args.policy_command == "generate":
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
    if args.policy_command == "apply":
        scopes = (
            build_principal(args),
            build_action(args),
            build_resource(args),
        )
        scenarios: list[Scenario] = []
        if not getattr(args, "no_scenarios", False):
            scenarios = workspace.load_scenarios(args.domain)
        compiled = workspace.apply_for_requirement(
            args.requirement_id, schema, scopes=scopes, scenarios=scenarios
        )
        return {"compiled": compiled.to_dict()}
    raise ConfigError(f"unknown policy command: {args.policy_command}")


def command_export(workspace: Workspace, args: Namespace) -> Any:
    """Export the domain's compiled Cedar to ``args.output``."""
    schema = workspace.load_schema(args.domain)
    workspace.validate_policies(args.domain, schema)
    output = workspace.export_domain(args.domain, args.output)
    return {"domain": args.domain, "output": str(output)}


def command_check(workspace: Workspace, args: Namespace) -> Any:
    """Run validation across every domain (or the specified one)."""
    if args.domain:
        domains = [args.domain]
    else:
        domains = sorted(
            {
                path.parent.name
                for path in workspace.root.glob("*/schema.json")
                if path.parent.name not in {".cedar-intent", ""}
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
        except CedarIntentError as error:
            results[domain] = {"passed": False, "error": str(error)}
    overall = all(result["passed"] for result in results.values())
    return {"passed": overall, "domains": results}


def command_verify(workspace: Workspace, args: Namespace) -> tuple[Any, int]:
    """Run verification for ``args.domain`` and return its report."""
    schema = workspace.load_schema(args.domain)
    report = workspace.verify_domain(args.domain, schema)
    exit_code = 1 if args.strict and not report.passed else 0
    return report.to_dict(), exit_code


def command_deploy(workspace: Workspace, args: Namespace) -> tuple[Any, int]:
    """Handle the three ``deploy`` subcommands."""
    if args.deploy_command == "push":
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
        return {"deployment": deployment_to_dict(record)}, 0
    if args.deploy_command == "bundle":
        manifest = workspace.build_bundle(args.domain)
        workspace.write_bundle(manifest, args.output)
        return {"domain": args.domain, "output": str(args.output)}, 0
    if args.deploy_command == "history":
        records = workspace.list_deployments(getattr(args, "domain", None))
        return {"deployments": [deployment_to_dict(record) for record in records]}, 0
    raise ConfigError(f"unknown deploy command: {args.deploy_command}")


def parse_headers(raw: list[str]) -> dict[str, str]:
    """Parse ``["Name: Value", ...]`` into a header dictionary."""
    parsed: dict[str, str] = {}
    for entry in raw:
        if ":" not in entry:
            raise ConfigError(f"invalid header (expected 'Name: Value'): {entry!r}")
        name, _, value = entry.partition(":")
        parsed[name.strip()] = value.strip()
    return parsed


def deployment_to_dict(record: Any) -> dict[str, Any]:
    """Serialize a :class:`DeploymentRecord` for CLI output."""
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
    """Select the right generator based on flags and environment."""
    model = args.model or os.getenv(MODEL_ENV_VAR)
    online = os.getenv(ONLINE_ENV_VAR, "").lower() in {"1", "true", "yes"}
    if getattr(args, "offline", False):
        return OfflineGenerator()
    if not online or not model:
        return OfflineGenerator()
    return LiteLLMGenerator(
        model=model,
        timeout=getattr(args, "timeout", 60),
        retries=getattr(args, "retries", 2),
        max_tokens=getattr(args, "max_tokens", 4096),
    )


def build_principal(args: Namespace) -> PrincipalScope:
    """Build a :class:`PrincipalScope` from parsed CLI arguments."""
    return PrincipalScope(
        kind=args.principal,
        type_name=args.principal_type,
        entity_id=args.entity_id,
        group_type=args.group_type,
        group_id=args.group_id,
    )


def build_action(args: Namespace) -> ActionScope:
    """Build an :class:`ActionScope` from parsed CLI arguments."""
    return ActionScope(
        kind=args.action,
        name=args.action_name,
        group=args.action_group,
    )


def build_resource(args: Namespace) -> ResourceScope:
    """Build a :class:`ResourceScope` from parsed CLI arguments."""
    return ResourceScope(
        kind=args.resource,
        type_name=args.resource_type,
        entity_id=args.entity_id,
        parent_type=args.parent_type,
        parent_id=args.parent_id,
    )


def humanize(payload: Any) -> str:
    """Render a structured CLI result for human-friendly output."""
    if not isinstance(payload, dict):
        return json.dumps(payload, indent=2, default=str)
    if "compiled" in payload:
        policy = payload["compiled"]
        return f"Compiled policy {policy['id']} ({policy['domain']})."
    if "draft" in payload:
        draft = payload["draft"]
        return (
            f"Draft policy {draft['id']} for requirement {draft['requirement_id']} "
            f"in domain {draft['domain']}."
        )
    if "domain" in payload and "output" in payload:
        return f"Exported {payload['domain']} to {payload['output']}."
    if "passed" in payload and "domains" in payload:
        domains = payload["domains"]
        failures = [name for name, info in domains.items() if not info["passed"]]
        if not failures:
            return f"All {len(domains)} domain(s) passed validation."
        return f"Failed: {', '.join(failures)}"
    if "initialized" in payload:
        return f"Initialized workspace at {payload['initialized']}."
    if "requirements" in payload:
        return join_or_none("Requirements", payload["requirements"])
    if "domains" in payload:
        return join_or_none("Domains", payload["domains"])
    if "id" in payload and "domain" in payload:
        return f"Stored requirement {payload['id']} for domain {payload['domain']}."
    return json.dumps(payload, indent=2, default=str)


def join_or_none(label: str, items: list[str]) -> str:
    """Render ``label: a, b, c`` or ``label: (none)`` depending on ``items``."""
    return f"{label}: {', '.join(items)}" if items else f"{label}: (none)"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
