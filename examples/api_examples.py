"""Runnable Python API recipes for cedar-intent.

Run with::

    python examples/api_examples.py

Each example uses an in-memory workspace, so no files are written to
disk. The examples are intentionally short so you can read the whole
file top to bottom.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cedar_intent import (
    ActionScope,
    CedarSchema,
    CompiledPolicy,
    DraftPolicy,
    LiteLLMGenerator,
    OfflineGenerator,
    PolicyIntent,
    PrincipalScope,
    Requirement,
    ResourceScope,
    Scenario,
    VerificationReport,
    Workspace,
    compile_intent,
    run_scenarios,
    validate_cedar,
    verify_policies,
)

PHOTOFLASH_SCHEMA = {
    "PhotoFlash": {
        "entityTypes": {
            "User": {
                "shape": {
                    "type": "Record",
                    "attributes": {"role": {"type": "String"}},
                }
            },
            "Photo": {
                "shape": {
                    "type": "Record",
                    "attributes": {"private": {"type": "Boolean"}},
                }
            },
        },
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


def make_workspace() -> Workspace:
    """Build a fresh in-memory workspace for the recipes."""
    return Workspace.in_memory(Path("/tmp/cedar-intent-example"))


def make_schema() -> CedarSchema:
    """Build a CedarSchema from the PhotoFlash mapping."""
    return CedarSchema.from_mapping(PHOTOFLASH_SCHEMA)


def make_requirement(identifier: str, body: str) -> Requirement:
    """Build a Requirement object with the given identifier and body."""
    return Requirement(
        id=identifier,
        text=body,
        domain="hr",
        source_path=Path(f"/tmp/{identifier}.md"),
    )


def recipe_compile_intent() -> None:
    """Compile a typed PolicyIntent into Cedar source."""
    intent = PolicyIntent(
        id="hr-hr-001",
        requirement_id="HR-001",
        effect="permit",
        principal=PrincipalScope(kind="is_type", type_name="PhotoFlash::User"),
        action=ActionScope(kind="named", name="viewPhoto", namespace="PhotoFlash"),
        resource=ResourceScope(kind="is_type", type_name="PhotoFlash::Photo"),
    )
    source = compile_intent(intent)
    print("compile_intent ->", source.cedar.replace("\n", " "))


def recipe_validate_cedar() -> None:
    """Validate a hand-written Cedar policy against the schema."""
    cedar = (
        'permit (principal is PhotoFlash::User, '
        'action == PhotoFlash::Action::"viewPhoto", '
        'resource is PhotoFlash::Photo);'
    )
    report = validate_cedar([cedar], make_schema())
    print("validate_cedar ->", report.passed, report.formatted)


def recipe_offline_generator(workspace: Workspace) -> tuple[DraftPolicy, Any]:
    """Run the deterministic OfflineGenerator on a draft policy."""
    schema = make_schema()
    draft = DraftPolicy(
        id="hr-hr-042",
        requirement=make_requirement(
            "HR-042",
            "Only admins can view photos when accessed from the office network.",
        ),
        principal=PrincipalScope(kind="is_type", type_name="PhotoFlash::User"),
        action=ActionScope(kind="named", name="viewPhoto", namespace="PhotoFlash"),
        resource=ResourceScope(kind="is_type", type_name="PhotoFlash::Photo"),
    )
    proposal = draft.generate(schema, OfflineGenerator())
    print("offline_generator ->", proposal.intent.effect, proposal.unresolved)
    return draft, proposal


def recipe_litellm_generator_factory() -> LiteLLMGenerator:
    """Build a LiteLLMGenerator bound to a specific model."""
    return LiteLLMGenerator(
        model="openai/gpt-4o",
        timeout=30,
        retries=2,
        max_tokens=1024,
        fallbacks=("anthropic/claude-3-5-sonnet",),
    )


def recipe_run_scenarios(workspace: Workspace, compiled: CompiledPolicy) -> None:
    """Run a small scenario suite against the compiled policy."""
    schema = make_schema()
    scenarios = [
        Scenario(
            name="alice-can-view",
            principal='PhotoFlash::User::"alice"',
            action='PhotoFlash::Action::"viewPhoto"',
            resource='PhotoFlash::Photo::"p1"',
            context={},
            expected="Allow",
        ),
        Scenario(
            name="bob-denied",
            principal='PhotoFlash::User::"bob"',
            action='PhotoFlash::Action::"viewPhoto"',
            resource='PhotoFlash::Photo::"p1"',
            context={},
            expected="Deny",
        ),
    ]
    report = run_scenarios([compiled.cedar], entities=[], scenarios=scenarios, schema=schema)
    print("run_scenarios ->", report.passed, [(r.scenario.name, r.actual) for r in report.results])


def recipe_verify_policies(workspace: Workspace) -> VerificationReport:
    """Run static verification on a domain's compiled policies."""
    schema = make_schema()
    policies = workspace.list_compiled_policies("hr")
    requirement_ids = [r.id for r in workspace.list_requirements("hr")]
    report = verify_policies(
        domain="hr",
        policies=policies,
        requirement_ids=requirement_ids,
        action_names=sorted(schema.action_names()),
        entity_type_names=sorted(schema.entity_type_names()),
    )
    print(
        "verify_policies ->",
        report.passed,
        [(f.kind, f.message) for f in report.findings],
    )
    return report


def recipe_deployment(workspace: Workspace) -> None:
    """Build a deployment bundle and write it to a local directory."""
    workspace.init_domain("hr")
    manifest = workspace.build_bundle("hr", metadata={"channel": "staging"})
    target = Path("/tmp/cedar-intent-example/dist")
    workspace.write_bundle(manifest, target)
    print(
        "deployment ->",
        target,
        "hash=",
        manifest.bundle_hash,
        "policies=",
        list(manifest.policy_ids),
    )


def main() -> None:
    workspace = make_workspace()
    workspace.init_domain("hr")
    workspace.repository.add_requirement(make_requirement("HR-042", "..."))

    print("== compile_intent ==")
    recipe_compile_intent()
    print("== validate_cedar ==")
    recipe_validate_cedar()
    print("== offline_generator ==")
    recipe_offline_generator(workspace)
    print("== litellm_generator_factory ==")
    generator = recipe_litellm_generator_factory()
    print("litellm_generator ->", generator.model, generator.fallbacks)
    print("== verify_policies ==")
    recipe_verify_policies(workspace)
    print("== deployment ==")
    recipe_deployment(workspace)


if __name__ == "__main__":
    main()
